# -*- coding: utf-8 -*-
"""角色点名与**契约原文注入**（方案 A：不碰 DSH preset）。

## 为什么要有这个脚本

9 个角色的契约写在 `agents/<id>-<slug>/AGENT.md`。原始做法是"主智能体凭记忆把契约抄进
`subagent` 的 prompt"——那正是本仓库最忌讳的事：**手抄会漂移，漂移无痕迹**。
本脚本把这一步变成机械动作，并留下可复核的痕迹：

1. **点名**：`list` / `show <role>` 直接从 `agents/*/agent.json` + `AGENT.md` 读，不缓存副本；
2. **注入**：`build` 生成一个**载荷文件**（= 子智能体 prompt 的全文），契约段落是
   `AGENT.md` 的**逐字节原文**，并附 `contract_sha256` / `payload_sha256`；
3. **留痕**：`--record` 把一条记录追加进 `work/role-spawns/spawn_ledger.jsonl`（append-only）：
   哪个角色、哪份契约（哈希）、什么任务（哈希）、什么时候、载荷落在哪 ⇒ 事后能回答
   "那次子智能体的依据是哪一版契约"；
4. **查漂移**：`verify <payload>` 用当前磁盘上的契约重算哈希，与载荷里记录的比对，
   不一致就**判漂移并拒绝使用该载荷**（fail-closed：宁可重建，不用旧契约跑新活）。

## 边界（必须说清，否则会误以为它能 spawn）

DSH 的 `subagent`/`subagent_fork` 是**模型侧工具**，脚本无法代替模型发起。本脚本只产出
**可注入的载荷 + 证据**；真正的 spawn 由主智能体用 `subagent(prompt=<载荷全文>)` 完成。
这也是方案 A 的取舍：不改动 `~/.dsh/.agent-presets/mems/` 的任何字节，
因此角色契约的修改**立即生效**（下次 spawn 现读），不需要重启 DSH、不需要新会话。

## 用法

```powershell
$py = 'work\\.venv\\Scripts\\python.exe'
& $py -B scripts\\spawn_role.py list
& $py -B scripts\\spawn_role.py show a8-verification-freeze
& $py -B scripts\\spawn_role.py build a8-verification-freeze --task-file work\\task.md --record
& $py -B scripts\\spawn_role.py verify work\\role-spawns\\<spawn_id>\\prompt.md
& $py -B scripts\\spawn_role.py ledger --tail 5
& $py -B scripts\\spawn_role.py check
```

退出码：`0` 成功；`2` 校验/漂移失败；`3` 载荷不可用（契约漂移、任务为空）；`4` 用法或角色不存在。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / "agents"
SPAWN_ROOT = REPO / "work" / "role-spawns"
LEDGER = SPAWN_ROOT / "spawn_ledger.jsonl"
ROLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
def say(msg: str = "") -> None:
    """控制台输出容错：GBK 控制台遇到 U+2212/⇒/emoji 会 UnicodeEncodeError 并打断整条管线。"""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        sys.stdout.write(msg.encode(enc, errors="replace").decode(enc, errors="replace") + "\n")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def rel(p: Path, root: Path | None = None) -> str:
    """相对仓库根的路径，**统一用正斜杠**（载荷会被不同平台/工具消费，反斜杠易被转义吃掉）。"""
    root = Path(root) if root is not None else REPO
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _width(s: object) -> int:
    """终端显示宽度（CJK 算 2 列），否则 `list` 的表格一定会错位。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(s))


def _pad(s: object, n: int) -> str:
    return str(s) + " " * max(0, n - _width(s))


def _canon_id(meta: dict, d: Path) -> str:
    """规范角色 id（如 `A5`）：`agent.json.role_id` > `id` > 目录名前缀。"""
    raw = meta.get("role_id") or meta.get("id") or d.name.split("-")[0]
    return str(raw).strip()


def find_roles() -> dict[str, Path]:
    """角色 id（小写，如 `a5`）→ 集合目录（以 `agent.json` 的存在为准，不靠目录名猜）。"""
    out: dict[str, Path] = {}
    if not AGENTS.is_dir():
        return out
    for d in sorted(p for p in AGENTS.iterdir() if p.is_dir()):
        aj = d / "agent.json"
        if not aj.is_file():
            continue
        try:
            meta = json.loads(aj.read_text(encoding="utf-8"))
        except Exception:
            continue
        out[_canon_id(meta, d).lower()] = d
    return out


def load_role(role: str) -> tuple[dict, Path, str, str]:
    """返回 (agent.json, 集合目录, AGENT.md 文本, AGENT.md sha256)。"""
    roles = find_roles()
    key = role.strip().lower()
    if key not in roles:
        # 也接受目录名（a8-verification-freeze）
        for rid, d in roles.items():
            if d.name.lower() == key:
                key = rid
                break
    if key not in roles:
        raise KeyError(role)
    d = roles[key]
    meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
    text = (d / "AGENT.md").read_text(encoding="utf-8")
    return meta, d, text, sha256_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    roles = find_roles()
    if not roles:
        say("找不到任何角色集合（agents/*/agent.json 为空）")
        return 3
    rows = []
    for rid, d in sorted(roles.items()):
        meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
        rows.append({"id": _canon_id(meta, d), "key": rid, "name": meta.get("name"),
                     "kind": meta.get("kind"), "status": meta.get("status"),
                     "dir": rel(d),
                     "one": meta.get("one_liner") or meta.get("one")})
    if args.json:
        sys.stdout.write(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    say("角色集合 %d 个（点名用 `show <key>`，key 也可用目录名；目录 %s）" % (len(rows), AGENTS))
    say("")
    for r in rows:
        say("  %s %s %s %s" % (_pad(r["id"], 4), _pad(r["name"], 22),
                               _pad(r["kind"], 10), r["status"]))
        say("       key=%s %s" % (_pad(r["key"], 24), r["one"] or ""))
    return 0


SECTION_RE = re.compile(r"^##\s*(\d+)\.")


def cmd_show(args: argparse.Namespace) -> int:
    try:
        meta, d, text, _ = load_role(args.role)
    except KeyError:
        say("未知角色：%r（先跑 list 看可用 id）" % args.role)
        return 4
    if args.section is not None:
        want = "## %d." % args.section
        lines = text.splitlines()
        out, grab = [], False
        for ln in lines:
            if SECTION_RE.match(ln):
                grab = ln.startswith(want)
            if grab:
                out.append(ln)
        if not out:
            say("角色 %s 没有第 %d 节" % (meta.get("id"), args.section))
            return 4
        text = "\n".join(out) + "\n"
    sys.stdout.write(text)
    return 0


def cmd_show_path(args: argparse.Namespace) -> int:
    try:
        _, d, _, sha = load_role(args.role)
    except KeyError:
        say("未知角色：%r" % args.role)
        return 4
    say("role_dir   : %s" % rel(d))
    say("AGENT.md   : %s  sha256=%s" % (rel(d / "AGENT.md"), sha))
    for name in ("agent.json", "README.md", "prompts/spawn.md"):
        p = d / name
        say("  %-16s %s%s" % (name, "OK  " if p.is_file() else "缺失", ""))
    return 0


PAYLOAD_HEADER = """# 子智能体任务载荷（由 scripts/spawn_role.py 生成）

> 把**本文件全文**作为 `subagent` 工具的 `prompt` 注入（不要摘要、不要改写）。
> 生成器不会替你 spawn：DSH 的 spawn 是模型侧动作。

| 项 | 值 |
|---|---|
| role_id | `{role_id}` |
| role_name | {role_name} |
| 角色目录 | `{role_dir}` |
| 契约文件 | `{contract_path}` |
| 契约 sha256 | `{contract_sha256}` |
| 任务 sha256 | `{task_sha256}` |
| spawn_id | `{spawn_id}` |
| 生成时刻(UTC) | {created_utc} |
| 生成器 sha256 | `{generator_sha256}` |

> 载荷自身的 sha256 记在**旁车** `spawn_record.json` 与账本里（不写进正文：正文里写自己的哈希
> 会形成无法自洽的自引用）。核对用 `spawn_role.py verify <载荷>`。

## 0. 给子智能体的注入须知

你是**独立子智能体**：看不到父会话的任何历史，本文件（角色契约 + 本次任务）就是你的全部输入。
仓库根：`{repo}`。必须遵守仓库 `AGENTS.md` 的红线与环境事实，尤其是：
没有证据不出数字（每个数值挂 `run_id`/`evidence_id`/`experiment_id`/`feedback_id`）；
判定类结论**以代码产出的裁决为准**，不得把 `inconclusive`/`None` 解释成通过；
不得声称"已验证等价于 COMSOL"；不得自行升级模型状态（放行权在人）。
需要改动仓库文件时，先只读、再小步改、并跑相关测试；**不要**改动 `~/.dsh` 下的任何预设文件。

## 1. 角色契约（`AGENT.md` 原文，逐字注入，不得改写）

<!-- BEGIN CONTRACT {contract_sha256} -->
{contract_text}
<!-- END CONTRACT {contract_sha256} -->

## 2. 本次任务

{task}

## 3. 交付要求（由角色声明派生）

- **角色声明的入口点**（只读引用；不得擅自改动其语义）：{entrypoints}
- **相关契约/schema**：{schemas}
- **相关测试**（改代码后必须跑）：{tests}
- **已知缺口**（角色自述；若你的结论落在这里，请明确指出）：{gaps}
- **并发边界**：可以 {can}；**不可以** {cannot}
- **停止条件**：{stops}——出现即停并上报，不要绕过。
- **交付格式**：先给结论（一句话 + 判定），再给**证据**（文件路径 + 行号或 sha256 + 复现命令），
  最后给「本次**没有**做/没有检查的」清单。**不要**给出无法溯源的数字。
"""


def build_payload(role: str, task: str, *, fields: dict[str, str] | None = None) -> tuple[str, dict]:
    meta, d, contract_text, contract_sha = load_role(role)
    fields = fields or {}
    if fields:
        extra = "\n".join("- %s = %s" % (k, v) for k, v in sorted(fields.items()))
        task = task.rstrip() + "\n\n### 任务参数\n\n" + extra + "\n"
    task_sha = sha256_bytes(task.encode("utf-8"))
    gen_sha = sha256_file(Path(__file__))
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    role_id = _canon_id(meta, d)
    spawn_id = "spawn-%s-%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                                   str(role_id).lower(), contract_sha[:8])
    body = PAYLOAD_HEADER.format(
        role_id=role_id, role_name=meta.get("name") or "", role_dir=rel(d),
        contract_path=rel(d / "AGENT.md"), contract_sha256=contract_sha,
        task_sha256=task_sha, spawn_id=spawn_id, created_utc=created, generator_sha256=gen_sha,
        repo=str(REPO), contract_text=contract_text, task=task,
        entrypoints=", ".join("`%s`" % x for x in (meta.get("entrypoints") or [])) or "（契约未声明）",
        schemas=", ".join("`%s`" % x for x in (meta.get("schemas") or [])) or "（无）",
        tests=", ".join("`%s`" % x for x in (meta.get("tests") or [])) or "（无）",
        gaps="; ".join(meta.get("gaps") or []) or "（角色未登记缺口）",
        can="; ".join((meta.get("concurrency") or {}).get("can") or []) or "（未声明）",
        cannot="; ".join((meta.get("concurrency") or {}).get("cannot") or []) or "（未声明）",
        stops="; ".join(meta.get("stop_conditions") or meta.get("stops") or []) or "（未声明）")
    # 任务模板里的 __OUT_DIR__ 占位替换成 spawn_id（在算载荷哈希之前完成，保证哈希自洽）
    body = body.replace("__OUT_DIR__", spawn_id)
    record = {"kind": "role_spawn", "spawn_id": spawn_id, "role_id": role_id,
              "role_name": meta.get("name"), "role_dir": rel(d),
              "contract_path": rel(d / "AGENT.md"),
              "contract_sha256": contract_sha, "task_sha256": task_sha,
              "payload_sha256": sha256_bytes(body.encode("utf-8")),
              "created_utc": created, "generator_sha256": gen_sha,
              "fields": fields, "task_excerpt": task.strip().splitlines()[0][:120] if task.strip() else ""}
    return body, record


def append_ledger(record: dict, ledger: Path | None = None) -> dict:
    """append-only：同一 `spawn_id` 内容相同 ⇒ 幂等；内容不同 ⇒ **拒收**。

    注意：`ledger` 默认值必须在使用时解析（不能写成 `ledger: Path = LEDGER`——
    默认参数在**定义时**求值，测试里 monkeypatch 模块变量会不生效，实测踩过）。
    """
    ledger = Path(ledger) if ledger is not None else LEDGER
    existing: dict[str, dict] = {}
    if ledger.is_file():
        for ln in ledger.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            if rec.get("spawn_id"):
                existing[str(rec["spawn_id"])] = rec
    sid = str(record["spawn_id"])
    if sid in existing:
        return {"status": "noop" if existing[sid] == record else "rejected",
                "reason": "" if existing[sid] == record else
                          "同一 spawn_id 内容不同 ⇒ 拒收（append-only：请重建载荷取新 id）",
                "ledger": str(ledger)}
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {"status": "appended", "ledger": str(ledger)}


def cmd_build(args: argparse.Namespace) -> int:
    if args.task_file:
        p = Path(args.task_file)
        if not p.is_file():
            say("找不到任务文件：%s" % p)
            return 4
        task = p.read_text(encoding="utf-8")
    else:
        task = args.task or ""
    if not task.strip():
        say("任务为空 ⇒ 拒绝生成载荷（空任务会让子智能体自由发挥）")
        return 4
    fields = {}
    for kv in args.field or []:
        if "=" not in kv:
            say("--field 需要 k=v 形式：%r" % kv)
            return 4
        k, v = kv.split("=", 1)
        fields[k.strip()] = v.strip()
    try:
        body, record = build_payload(args.role, task, fields=fields)
    except KeyError:
        say("未知角色：%r（先跑 list）" % args.role)
        return 4

    out_dir = Path(args.out_dir) if args.out_dir else SPAWN_ROOT / record["spawn_id"]
    if args.dry_run:
        say("[dry-run] role=%s spawn_id=%s" % (record["role_id"], record["spawn_id"]))
        say("  contract_sha256=%s" % record["contract_sha256"])
        say("  payload_sha256 =%s  bytes=%d" % (record["payload_sha256"], len(body.encode("utf-8"))))
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = out_dir / "prompt.md"
    prompt_path.write_text(body, encoding="utf-8")
    record["payload_path"] = str(prompt_path)
    (out_dir / "spawn_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    say("role=%s spawn_id=%s" % (record["role_id"], record["spawn_id"]))
    say("  prompt : %s  (%d B)" % (prompt_path, len(body.encode("utf-8"))))
    say("  sha256 : contract=%s payload=%s"
        % (record["contract_sha256"][:16], record["payload_sha256"][:16]))
    if args.record:
        res = append_ledger(record)
        say("  ledger : %s %s" % (res["status"], res.get("reason", "")))
        if res["status"] == "rejected":
            return 2
    say("")
    say("下一步（主智能体执行）：把 prompt.md 全文作为 subagent 的 prompt 注入，"
        "并把 spawn_id 记进交付说明。")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """用**当前磁盘上的契约**重算哈希，与载荷/账本记录比对（fail-closed）。"""
    p = Path(args.payload)
    if p.is_dir():
        p = p / "prompt.md"
    if not p.is_file():
        say("找不到载荷：%s" % p)
        return 4
    body = p.read_text(encoding="utf-8")
    rec_path = p.with_name("spawn_record.json")
    rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else {}
    m = re.search(r"\| 契约 sha256 \| `([0-9a-f]{64})` \|", body)
    role_m = re.search(r"\| role_id \| `([^`]+)` \|", body)
    if not m or not role_m:
        say("载荷格式不符（缺 role_id / 契约 sha256）⇒ 不认，请重建")
        return 2
    want, role_id = m.group(1), role_m.group(1)
    try:
        _, d, contract_text, got = load_role(role_id)
    except KeyError:
        say("载荷里的角色 %r 在仓库里已不存在 ⇒ 判失败" % role_id)
        return 2
    drift = (want != got)
    say("载荷 : %s" % p)
    say("角色 : %s  契约 : %s" % (role_id, rel(d / "AGENT.md")))
    say("契约哈希：载荷=%s 现算=%s  ⇒ %s"
        % (want[:16], got[:16], "DRIFT（拒绝使用该载荷）" if drift else "MATCH"))
    if "<!-- BEGIN CONTRACT" in body:
        seg = body.split("<!-- BEGIN CONTRACT", 1)[1].split("-->", 1)[1]
        seg = seg.split("<!-- END CONTRACT", 1)[0]
        seg = seg.strip("\n")
        same_text = (seg == contract_text.strip("\n"))
        say("契约正文逐字节比对：%s" % ("一致" if same_text else "不一致"))
        drift = drift or not same_text
    if rec:
        say("账本记录：spawn_id=%s payload_sha256=%s" % (rec.get("spawn_id"), str(rec.get("payload_sha256"))[:16]))
        cur = sha256_bytes(body.encode("utf-8"))
        if rec.get("payload_sha256") and rec["payload_sha256"] != cur:
            say("载荷与账本记录不符（载荷被改过）⇒ 判失败")
            drift = True
    if drift:
        say("结论：**契约漂移** ⇒ 该载荷不得用于 spawn；请重新 build。")
        return 2
    say("结论：载荷与当前契约一致，可用于 spawn。")
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    if not LEDGER.is_file():
        say("账本还不存在：%s" % LEDGER)
        return 0
    lines = [x for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]
    say("账本 %s（%d 条，append-only）" % (rel(LEDGER), len(lines)))
    for ln in lines[-args.tail:]:
        r = json.loads(ln)
        say("  %s  role=%-3s contract=%s  %s"
            % (r.get("spawn_id"), r.get("role_id"), str(r.get("contract_sha256"))[:8],
               (r.get("task_excerpt") or "")[:70]))
    return 0

def cmd_check(args: argparse.Namespace) -> int:
    """离线自检：集合完整、声明路径存在、名册/索引覆盖、生成器一致。"""
    problems: list[str] = []
    roles = find_roles()
    say("角色 %d 个" % len(roles))
    for rid, d in sorted(roles.items()):
        meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
        for name in ("AGENT.md", "agent.json", "prompts/spawn.md", "README.md"):
            if not (d / name).is_file():
                problems.append("%s 缺 %s" % (rid, name))
        for key in ("entrypoints", "schemas", "tests"):
            for rel in meta.get(key) or []:
                cand = REPO / rel
                if not cand.exists():
                    # 目录型/通配声明（如 work/runs/xxx/）允许不存在
                    if rel.endswith("/") or any(ch in rel for ch in "*?"):
                        continue
                    problems.append("%s 声明的不存在：%s=%s" % (rid, key, rel))
        text = (d / "AGENT.md").read_text(encoding="utf-8")
        for i in range(10):
            if ("## %d." % i) not in text:
                problems.append("%s AGENT.md 缺第 %d 节" % (rid, i))
    roster = (AGENTS / "README.md")
    if roster.is_file():
        rt = roster.read_text(encoding="utf-8")
        for rid in roles:
            d = roles[rid]
            if d.name not in rt:
                problems.append("名册 agents/README.md 未覆盖 %s" % d.name)
    if problems:
        say("发现问题 %d 条：" % len(problems))
        for x in problems:
            say("  - %s" % x)
        return 2
    say("结论：%d 个角色集合完整、声明路径存在、名册覆盖齐备" % len(roles))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="角色点名 / 契约原文注入 / 账本（方案 A）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出 9 个角色")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="打印角色契约（可只打某一节）")
    p.add_argument("role")
    p.add_argument("--section", type=int, default=None)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("where", help="打印角色目录与四件套状态")
    p.add_argument("role")
    p.set_defaults(fn=cmd_show_path)

    p = sub.add_parser("build", help="生成可注入的子智能体载荷")
    p.add_argument("role")
    p.add_argument("--task", default=None)
    p.add_argument("--task-file", default=None)
    p.add_argument("--field", action="append", default=[], help="附加任务参数 k=v（可重复）")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--record", action="store_true", help="追加进 spawn 账本")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("verify", help="核对载荷契约哈希（漂移即拒绝）")
    p.add_argument("payload")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("ledger", help="查看 spawn 账本尾部")
    p.add_argument("--tail", type=int, default=10)
    p.set_defaults(fn=cmd_ledger)

    p = sub.add_parser("check", help="集合完整性/声明路径/名册覆盖离线自检")
    p.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
