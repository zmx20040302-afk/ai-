# -*- coding: utf-8 -*-
"""失败通道：把「平台没做成的这件事」变成一份**可发送出去的分析包**。

用户要求（2026-09-30）：「完善该页面，当出现无法完成的任务时可以发送过来进行分析和处理」。
口径是用户当场逐项选定的，本模块**只做这三条**：

1. **收哪些**（全选）：任务失败 / 超时 / 取消、代理拒答、页面脚本异常、服务不可用、接口异常，
   外加一个人工上报入口；
2. **发到哪**：**只生成自包含分析包**（`INCIDENT.md` + `incident.json`，页面一键复制），
   由人发给 Codex 或助手。**不外发**：本模块不发起任何网络请求 ⇒ 离线模式下功能完整可用；
3. **包里放什么**（用户只勾了两项）：① 现象 + **原始错误全文（含堆栈）**；
   ② 当时的**输入与调用**（端点 / 参数 / 复现命令）。
   ⚠️ **用户明确没勾**日志尾部、其它在跑任务、环境事实、「我已排除的可能」⇒
   本模块**不加**这些。加了会让包变成"谁都不看的流水账"，也是对用户口径的擅自扩大。

红线（与 `AGENTS.md` 对齐）：
* 包内**只有事实，没有任何分析结论**，并在包里写明「接收方的判断不得改变裁定、
  模型状态或放行」（红线 5：人保留放行权）；
* **密钥一律脱敏**：错误文本里可能夹着 API key / token（本项目凭据就在磁盘上），
  脱敏在**入库前**做，避免台账本身成为泄露面；
* 台账 **append-only**（修正靠新增，不覆盖）；包文件**已存在即拒绝**（与冻结同款 fail-closed）。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
LEDGER = REPO / "work/logs/incidents.jsonl"
PACKAGE_ROOT = REPO / "work/runs/incidents"

SCHEMA = "incident_package_v1"

#: 类别 → 中文名。**未登记的类别一律拒收**（免得前端随手发明一个没人认识的 kind）。
KINDS: dict[str, str] = {
    "task_timeout": "任务超时（无结果可用）",
    "task_failed": "任务失败",
    "task_cancelled": "任务被取消",
    "refusal": "代理拒答（超出适用范围）",
    "page_error": "页面脚本异常",
    "api_error": "接口异常（服务端未处理）",
    "service_unavailable": "服务不可用（控制台没应答）",
    "manual": "人工上报",
}

#: 每个字段的字符上限（超出即**显式**截断并留痕，绝不静默丢内容）。
CAPS: dict[str, int] = {
    "symptom": 2000, "error_text": 20000, "stack": 10000, "repro": 2000,
    "command": 1000, "endpoint": 300, "source": 60,
}
#: 参数里单个字符串值的上限 / 键数上限
PARAM_STR_CAP = 600
PARAM_KEYS_CAP = 60

NO_ANALYSIS = (
    "本包**只含现象与原始错误全文**，不含任何分析结论或判定。"
    "接收方（人或模型）给出的判断**不得**改变裁定、模型状态或放行 —— "
    "放行权在人（AGENTS.md 红线 5）；也不得据此宣称任何能力已验证。"
)

_SECRETS: tuple[tuple[re.Pattern[str], str], ...] = (
    # `sk-…`（DeepSeek/OpenAI 风格）；先于通用 key 规则，避免被后面的规则切碎
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-<REDACTED>"),
    # `Authorization: Bearer <x>`
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer <REDACTED>"),
    # `api_key=…` / `"token": "…"` / `password: …` / 光秃秃的 `key=…`
    # ⚠️ `key` 必须单列：自检里 `error_text="key=SHOULD-NOT-APPEAR-1234"` 就漏过了一版
    #    （只有 `api[_-]?key` 时不匹配裸 `key=`）—— 是自检的脱敏用例当场抓到的。
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|token|key|password|passwd|secret)"
                r"\b\s*[:=]\s*[\"']?([^\s\"',}]{4,})"), r"\1=<REDACTED>"),
    # URL query：`?token=…` / `&key=…`
    (re.compile(r"(?i)([?&](?:token|key|api_key|apikey)=)[^\s&\"']+"), r"\1<REDACTED>"),
)

#: **按参数名**判密钥。只靠文本模式抓不住 `{"token": "…"}` 这种"键值分开"的形态 ——
#: 实测初版就漏了这个（冒烟测试里 `token` 的值原样进了台账与包）。
#: `key` 单列也一起判：宁可多脱敏一个普通 `key` 参数，也不漏一个真密钥（fail-closed）。
_SECRET_KEY = re.compile(
    r"(?i)(^|[_\-.\[\]])(api[_-]?key|access[_-]?token|token|key|secret|"
    r"password|passwd|authorization|credential|bearer)([_\-.\[\]]|$)")



def redact(text: object) -> tuple[str, int]:
    """脱敏；返回（文本, 命中处数）。非字符串走 `str()`，None 变空串。"""
    if text is None:
        return "", 0
    s = text if isinstance(text, str) else str(text)
    n = 0
    for pat, rep in _SECRETS:
        s, k = pat.subn(rep, s)
        n += k
    return s, n


def clip(text: object, cap: int) -> tuple[str, bool, int]:
    """按上限截断（保头**与**尾：堆栈的关键信息在尾部，现象的关键信息在头部）。"""
    s = "" if text is None else (text if isinstance(text, str) else str(text))
    if len(s) <= cap:
        return s, False, len(s)
    head = int(cap * 0.6)
    tail = cap - head
    return (s[:head] + "\n…[本字段原长 %d 字符，中间省略 %d 字符]…\n" % (len(s), len(s) - cap)
            + s[-tail:]), True, len(s)


def _clean(text: object, field: str) -> tuple[str, int, bool]:
    s, n_red = redact(text)
    s, trunc, _ = clip(s, CAPS.get(field, 2000))
    return s, n_red, trunc


def _clean_params(params: object) -> tuple[object, int, bool]:
    """递归脱敏参数：**按键名**判密钥（整值替换）＋ 按文本模式扫值。"""
    n_red, trunc = 0, False

    def walk(v: object, depth: int = 0, key: str = "") -> object:
        nonlocal n_red, trunc
        if key and _SECRET_KEY.search(str(key)):
            n_red += 1
            return "<REDACTED：参数名像密钥，整值不记录>"
        if depth > 6:
            trunc = True
            return "<深度超限>"
        if isinstance(v, str):
            s, k = redact(v)
            n_red += k
            if len(s) > PARAM_STR_CAP:
                s, trunc = s[:PARAM_STR_CAP] + "…[截断]", True
            return s
        if isinstance(v, dict):
            if len(v) > PARAM_KEYS_CAP:
                trunc = True
                v = dict(list(v.items())[:PARAM_KEYS_CAP])
            return {str(k): walk(x, depth + 1, str(k)) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            if len(v) > PARAM_KEYS_CAP:
                trunc = True
                v = list(v)[:PARAM_KEYS_CAP]
            return [walk(x, depth + 1, "") for x in v]
        return v

    return walk(params), n_red, trunc


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_id(kind: str, ts: str | None = None, rand: str | None = None) -> str:
    """`inc-<UTC 时间>-<kind>-<6hex>`。`rand` 只为测试可复现而存在。"""
    stamp = re.sub(r"[-:]", "", (ts or _now()))
    tail = rand if rand is not None else os.urandom(3).hex()
    return "inc-%s-%s-%s" % (stamp, kind.replace("_", ""), tail)


def synth_repro(*, task: str = "", args: object = None, endpoint: str = "",
                method: str = "POST", params: object = None, port: int = 8877) -> str:
    """由**已知的**调用信息推导复现命令；推不出来就返回空串（**不编造**）。"""
    if task:
        payload = json.dumps(args if args is not None else {}, ensure_ascii=False)
        return ('python -B scripts/webapp_server.py --exec-task %s '
                '--args-json %s --out-json %%TEMP%%\\result.json' % (task, _q(payload)))
    if endpoint:
        if method.upper() == "GET":
            q = ""
            if isinstance(params, dict) and params:
                q = "?" + urllib_query(params)
            return 'curl.exe -s %s' % _q("http://127.0.0.1:%d%s%s" % (port, endpoint, q))
        body = json.dumps(params if params is not None else {}, ensure_ascii=False)
        return ('curl.exe -s -X POST %s -H %s -d %s'
                % (_q("http://127.0.0.1:%d%s" % (port, endpoint)),
                   _q("Content-Type: application/json"), _q(body)))
    return ""


def _q(s: str) -> str:
    """Windows 命令行参数常用双引号包裹（内部引号转义）。"""
    return '"' + s.replace('"', '\\"') + '"'


def urllib_query(d: dict) -> str:
    import urllib.parse
    return urllib.parse.urlencode({k: v for k, v in d.items()}, doseq=True)


def ledger_path() -> pathlib.Path:
    """台账路径。三级优先：env 覆盖 > 测试期临时文件 > 生产台账。

    * `MEMS_INCIDENTS_LEDGER`：**临时脚本/冒烟测试必须用它**（或设 `PYTEST_CURRENT_TEST`）。
      实测教训（2026-09-30）：我用 `python -c` 做冒烟测试时**没设**这两个，
      于是真台账 `work/logs/incidents.jsonl` 里落下一条 `task_timeout`，
      与真实超时**无法区分** —— 已删除该单行文件并在 `docs/INDEX-records-and-rulings.md` §83 留痕。
    * `PYTEST_CURRENT_TEST`（pytest 自己设）：写到临时目录，沿用 `_append_task_log` 的既有判据。
      注意它**只在 pytest 进程内**存在 ⇒ 裸 `python -c` 不受保护，这就是上面那条教训的成因。
    """
    env = os.environ.get("MEMS_INCIDENTS_LEDGER")
    if env:
        return pathlib.Path(env)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return pathlib.Path(tempfile.gettempdir()) / "memshop-incidents-under-test.jsonl"
    return LEDGER


def record(kind: str, symptom: str, *, source: str = "console", endpoint: str = "",
           method: str = "", params: object = None, task: str = "", args: object = None,
           error_text: str = "", stack: str = "", repro: str = "", command: str = "",
           incident_id: str | None = None) -> dict:
    """登记一条「没做成的事」。**未登记的类别拒收**；返回值就是入库的记录。"""
    if kind not in KINDS:
        raise ValueError("未登记的失败类别：%r（合法值：%s）"
                         % (kind, "/".join(sorted(KINDS))))
    n_red = 0
    trunc: dict[str, int] = {}
    out: dict[str, object] = {}
    for field, raw in (("symptom", symptom), ("error_text", error_text),
                       ("stack", stack), ("command", command),
                       ("endpoint", endpoint), ("source", source)):
        s, k, tr = _clean(raw, field)
        out[field] = s
        n_red += k
        if tr:
            trunc[field] = len("" if raw is None else str(raw))
    # ⚠️ `repro` **不能**放进上面的循环再 `rec.update(out)` 覆盖：
    # 初版就是这么写的，`out["repro"]`（空串）把推导出来的复现命令**整个盖掉**，
    # 冒烟测试里表现为「复现命令为空」——而那是这个包最有用的字段之一。
    repro_clean, k, tr = _clean(repro, "repro")
    n_red += k
    if tr:
        trunc["repro"] = len(repro or "")
    p_out, k, tr = _clean_params(params if params is not None else {})
    n_red += k
    if tr:
        trunc["params"] = 1
    a_out, k, tr = _clean_params(args if args is not None else {})
    n_red += k
    if tr:
        trunc["args"] = 1

    rec: dict[str, object] = {
        "incident_id": incident_id or new_id(kind),
        "ts": _now(), "kind": kind, "kind_zh": KINDS[kind],
        "task": task, "method": (method or "").upper(),
        "params": p_out, "args": a_out,
        "repro": repro_clean or synth_repro(task=task, args=a_out, endpoint=out["endpoint"],
                                            method=method or "POST", params=p_out),
        "redacted_hits": n_red, "truncated": trunc,
        "no_analysis": NO_ANALYSIS,
    }
    rec.update(out)
    _append(rec)
    return rec


def _append(rec: dict) -> None:
    target = ledger_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        # 台账写不进去不能反过来把原始错误吞掉：调用方拿到的 rec 仍然有效
        pass


def load(limit: int = 50) -> dict:
    """读台账（**最新的在前**）；坏行只统计不崩。"""
    p = ledger_path()
    recs: list[dict] = []
    n_bad = 0
    if p.is_file():
        try:
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if not ln.strip():
                    continue
                try:
                    recs.append(json.loads(ln))
                except ValueError:
                    n_bad += 1
        except OSError:
            pass
    recs.reverse()
    return {"n_total": len(recs), "n_bad_lines": n_bad, "limit": max(1, int(limit)),
            "items": recs[:max(1, int(limit))],
            "ledger": _rel(p), "kinds": KINDS}


def counts() -> dict:
    r = load(limit=10 ** 9)
    by: dict[str, int] = {}
    for it in r["items"]:
        k = str(it.get("kind") or "?")
        by[k] = by.get(k, 0) + 1
    return {"n_total": r["n_total"], "by_kind": by, "n_bad_lines": r["n_bad_lines"]}


def get(incident_id: str) -> dict | None:
    r = load(limit=10 ** 9)
    for it in r["items"]:
        if it.get("incident_id") == incident_id:
            return it
    return None


def _rel(p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(p)


def render_md(rec: dict) -> str:
    """把一条记录渲染成**可直接发出去**的 markdown。"""
    L: list[str] = []
    L.append("# 失败分析包 %s" % rec.get("incident_id", "?"))
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| 类别 | %s（`%s`） |" % (rec.get("kind_zh", "?"), rec.get("kind", "?")))
    L.append("| 时间 | %s |" % rec.get("ts", "?"))
    L.append("| 来源组件 | %s |" % (rec.get("source") or "?"))
    if rec.get("task"):
        L.append("| 任务 | `%s` |" % rec["task"])
    if rec.get("endpoint"):
        L.append("| 端点 | `%s %s` |" % (rec.get("method") or "", rec["endpoint"]))
    L.append("| 脱敏命中 | %s 处（已替换为 `<REDACTED>`） |" % rec.get("redacted_hits", 0))
    if rec.get("truncated"):
        L.append("| 字段截断 | %s（已显式标注，未静默丢弃） |"
                 % ", ".join("%s(原长%s)" % (k, v) for k, v in
                             sorted(dict(rec["truncated"]).items())))
    L.append("")
    L.append("## 1. 现象")
    L.append("")
    L.append(rec.get("symptom") or "（未提供）")
    L.append("")
    L.append("## 2. 原始错误全文（含堆栈）")
    L.append("")
    L.append("```text")
    L.append(rec.get("error_text") or "（该事件没有错误文本：例如拒答是**正常**的 fail-closed 行为）")
    L.append("```")
    if rec.get("stack"):
        L.append("")
        L.append("### 2.1 堆栈")
        L.append("")
        L.append("```text")
        L.append(str(rec["stack"]))
        L.append("```")
    L.append("")
    L.append("## 3. 当时的输入与调用")
    L.append("")
    L.append("```json")
    L.append(json.dumps({"params": rec.get("params") or {},
                         "args": rec.get("args") or {}},
                        ensure_ascii=False, indent=1))
    L.append("```")
    L.append("")
    L.append("复现命令：")
    L.append("")
    if rec.get("repro"):
        L.append("```powershell")
        L.append(str(rec["repro"]))
        L.append("```")
    else:
        L.append("未自动推导出复现命令（缺端点/任务与参数）—— **不编造**，请向提报人索取。")
    L.append("")
    L.append("## 4. 本包**不含**什么（按用户口径）")
    L.append("")
    L.append("* 不含日志尾部、其它在跑任务、环境事实；")
    L.append("* 不含任何分析结论。")
    L.append("")
    L.append("> " + str(rec.get("no_analysis") or NO_ANALYSIS))
    L.append("")
    return "\n".join(L)


def package(incident_id: str) -> dict:
    """只生成文本（不落盘）：`md` + `json` + md 的 sha256。"""
    rec = get(incident_id)
    if rec is None:
        return {"error": "没有这条记录：%s" % incident_id, "incident_id": incident_id}
    md = render_md(rec)
    import hashlib
    body = {
        "_package": {"schema": SCHEMA, "generated_at": _now(),
                     "md_sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(),
                     "no_analysis": rec.get("no_analysis") or NO_ANALYSIS,
                     "sent_to": "由人决定（本控制台不外发）"},
        "incident": rec,
    }
    return {"incident_id": incident_id, "md": md, "json": body,
            "md_sha256": body["_package"]["md_sha256"],
            "md_bytes": len(md.encode("utf-8")), "record": rec}


def package_root() -> pathlib.Path:
    """包目录。与 `ledger_path()` 同款三级优先（env > 测试临时 > 生产）。

    为什么要可重定向：自检（`--selftest`，**不在 pytest 下**）会真的写一次包来验证
    「拒绝覆盖」；若没有这个开关，自检就会往 `work/runs/incidents/` 里塞演示产物。
    """
    env = os.environ.get("MEMS_INCIDENTS_ROOT")
    if env:
        return pathlib.Path(env)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return pathlib.Path(tempfile.gettempdir()) / "memshop-incident-packages-under-test"
    return PACKAGE_ROOT


def write_package(incident_id: str, out_root: str | pathlib.Path | None = None) -> dict:
    """把包写进 `work/runs/incidents/<id>/`；**已存在即拒绝**（append-only，不覆盖）。"""
    pk = package(incident_id)
    if "error" in pk:
        return pk
    explicit = out_root is not None
    root = pathlib.Path(out_root) if explicit else package_root()
    if not root.is_absolute():
        root = REPO / root
    # 守卫：**人显式指定的**目录必须在 work/ 下（防止把产物写到仓库外/系统目录）；
    # env / 测试重定向到的临时目录不适用（那不是仓库产物）。fail-closed 不放松。
    if explicit:
        try:
            root.resolve().relative_to((REPO / "work").resolve())
        except ValueError:
            return {"error": "输出目录必须在 work/ 下：%s" % root,
                    "incident_id": incident_id}
    d = root / incident_id
    md_p, js_p = d / "INCIDENT.md", d / "incident.json"
    existing = [str(p) for p in (md_p, js_p) if p.is_file()]
    if existing:
        return {"error": "包已存在，拒绝覆盖（append-only）", "incident_id": incident_id,
                "existing": existing}
    d.mkdir(parents=True, exist_ok=True)
    with md_p.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(pk["md"])
    with js_p.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(pk["json"], ensure_ascii=False, indent=1) + "\n")
    return {"incident_id": incident_id, "dir": _rel(d),
            "md_path": _rel(md_p), "json_path": _rel(js_p),
            "md_sha256": pk["md_sha256"], "md": pk["md"], "json": pk["json"],
            "md_bytes": pk["md_bytes"], "not_sent": "本控制台**不外发**；请由人发给 Codex 或助手"}
