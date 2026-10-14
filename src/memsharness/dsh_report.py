# -*- coding: utf-8 -*-
"""把一条失败**直接上报给 DeepSeek Harness（DSH）**做分析。

用户要求（2026-09-30）：「出现异常页面可以直接进行上报，直接上报给 deep seek harness」。
口径（用户当场选定，**别擅自放宽**）：

1. **只读分析**：DSH 只给根因与修复建议，**不得修改/创建/删除任何文件**（唯一允许的写入
   是它自己的 `analysis.md`，在这个上报目录里）；
2. **只在他点按钮时**上报 —— 不做任何自动触发（不做"重复 3 次就自动跑"）；
3. **离线模式禁止**上报：控制台离线时承诺"不发任何网络请求"，而 headless DSH 会联网调模型
   ⇒ 这个动作只允许在 DeepSeek 模式下发起（门禁在 `webapp_server`，因为模式是它的状态）。

### 为什么用 `dsh --profile headless`
它是 DSH **自带的正规接口**（`@deepseek-ai/dsh-headless` 这个 bundle）：跑一个任务、打印最终
答案、然后退出；不开端口、不留后台服务、与其它界面共用同一套模型/工具/安全默认值。
**不是**去调 DSH 的内部 RPC（那需要猜内部协议，本仓库明令不许猜内部）。

### 实测过的环境事实（别凭印象改）
* `dsh` **不在 PATH 上**（实测 `Get-Command dsh` 找不到）⇒ 需要 `DSH_BIN` 显式指定，
  或去 npx 缓存里**发现**（`_npx/*/node_modules/@deepseek-ai/dsh/lib/bin.js`，取最新的一个）。
  找不到就**如实报错**并告诉用户怎么指定，**不猜路径**。
* `--profile headless` 是内置模板（`--dump-default-config` 能打印出
  `@deepseek-ai/dsh-headless` 的 patch 层 + `headless-runner`），无需先手工初始化。
* 调用形态：`node <bin.js> --profile headless <任务文本>`（任务文本走位置参数）。
  任务文本**只放一句指路**（去读 prompt.md），因为整包 markdown 塞进 argv 会太长。
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
REPORT_LOG = REPO / "work/logs/dsh_reports.jsonl"

#: 正在跑的上报：report_id → {"proc": Popen, "log": 台账路径}。
#: **连台账路径一起存**：终态回填常常发生在**另一个线程、且环境变量已被改回之后**
#: （实测：测试的后台线程把一条 finished_at 写进了**生产**台账，因为它重新读了一次 env）。
_PROCS: dict[str, dict] = {}
_PROC_LOCK = threading.Lock()

#: 只读分析的硬约束（写进 prompt，且**逐条**被测试断言，因为这是用户选的口径）
READONLY_RULES = (
    "只做分析。**不得修改、创建、删除仓库里的任何文件**（唯一允许的写入是本次上报目录下的 analysis.md）。",
    "不得运行任何会改变状态的命令（不跑测试以外的写操作、不 git 提交、不动 work/ 下的产物）。",
    "不得改变任何裁定、模型状态或放行结论 —— 放行权在人（AGENTS.md 红线 5）。",
    "你的判断必须有依据：指出依据来自哪个文件/哪一行/哪条日志；**证据不足就直说不确定，不许猜**。",
)


def find_dsh() -> tuple[list[str] | None, str]:
    """解析 `dsh` 怎么调；返回（argv 前缀, 说明）。找不到就返回 (None, 原因)，**不猜**。"""
    env = (os.environ.get("DSH_BIN") or "").strip()
    if env:
        p = pathlib.Path(env)
        if p.suffix.lower() in (".js", ".cjs", ".mjs"):
            # 直接给 .js 时用 node 起（DSH 的 bin.js 就是这种）
            return ["node", str(p)], "DSH_BIN（node 脚本）"
        if p.suffix.lower() in (".py", ".pyw"):
            # 指向 .py 时用当前解释器起：测试用的替身就是这么给的
            # （Windows 不能直接执行 .py，不处理的话会 OSError）
            return [sys.executable, str(p)], "DSH_BIN（python 脚本）"
        if p.is_file():
            return [str(p)], "DSH_BIN"
        return None, "DSH_BIN 指向的文件不存在：%s" % env
    import shutil
    w = shutil.which("dsh")
    if w:
        return [w], "PATH 上的 dsh"
    # npx 缓存里**发现**（与 npx 自己用的位置一致）；取最新修改的那个。
    # ⚠️ 这条**只在显式允许时**才用（`MEMS_DSH_ALLOW_DISCOVERED=1`）：
    # 否则任何没设 DSH_BIN 的测试/脚本都会"顺手"找到真实 dsh 并把它拉起来
    # —— 2026-09-30 实测真的发生过（一次冒烟测试 + 一次来源不明的 11:48:43 进程），
    # 每一次都是真花 token。控制台自己在启动时设这个变量（见 `webapp_server.main`）。
    if (os.environ.get("MEMS_DSH_ALLOW_DISCOVERED") or "").strip() not in ("1", "true", "yes"):
        return None, ("没设 DSH_BIN，且未允许自动发现 dsh（需 MEMS_DSH_ALLOW_DISCOVERED=1）。"
                      "请设 DSH_BIN 指向 dsh；控制台自己会打开这个开关。")
    base = pathlib.Path(os.environ.get("LOCALAPPDATA") or (pathlib.Path.home() / "AppData/Local"))
    pat = str(base / "npm-cache" / "_npx" / "*" / "node_modules" / "@deepseek-ai"
              / "dsh" / "lib" / "bin.js")
    cands = [pathlib.Path(p) for p in glob.glob(pat) if pathlib.Path(p).is_file()]
    if cands:
        newest = max(cands, key=lambda p: p.stat().st_mtime)
        return ["node", str(newest)], "npx 缓存中发现的 bin.js"
    return None, ("找不到 dsh：不在 PATH、npx 缓存里也没有。"
                  "请设环境变量 DSH_BIN 指向 dsh 可执行文件或 lib/bin.js。")


def build_prompt(incident_id: str, package_md: str, *, prompt_path: pathlib.Path) -> str:
    """给 DSH 的任务文本：口径 + 硬约束 + 包全文，并要求它把结论写到 analysis.md。"""
    L: list[str] = []
    L.append("# 任务：分析一条 MESM 平台失败（**只读**）")
    L.append("")
    L.append("有人从 MEMS 平台控制台的「失败通道」把 `%s` 上报给你。"
             "下面是**失败分析包全文**（现象 / 原始错误全文 / 当时的输入与调用）。" % incident_id)
    L.append("")
    L.append("## 你必须遵守（这是提报人的口径，不是建议）")
    L.append("")
    for i, r in enumerate(READONLY_RULES, 1):
        L.append("%d. %s" % (i, r))
    L.append("")
    L.append("## 输出格式（缺一项就算没交付）")
    L.append("")
    L.append("1. **最可能的根因**（按可能性排序，每条注明依据来自哪里）；")
    L.append("2. **要确认它还需要什么证据**（具体到命令或文件）；")
    L.append("3. **建议的修复**（写成可审阅的补丁描述或确切改动点，**不要直接改**）；")
    L.append("4. **你不确定的地方**（列出来，别用模糊表述掩盖）。")
    L.append("")
    L.append("另外：把最终分析**同时**写到 `%s`（这是唯一允许的写入）；"
             "写不了也没关系，你的最终答复会被控制台捕获。" % (prompt_path.parent / "analysis.md"))
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 失败分析包全文")
    L.append("")
    L.append(package_md)
    return "\n".join(L)


def new_report_id(ts: str | None = None) -> str:
    stamp = re.sub(r"[-:]", "", ts or time.strftime("%Y-%m-%dT%H:%M:%S"))
    return "dshr-%s-%s" % (stamp, os.urandom(3).hex())


def report_root(incident_id: str, report_id: str, out_root: str | None = None) -> pathlib.Path:
    base = pathlib.Path(out_root) if out_root else REPO / "work/runs/incidents"
    if not base.is_absolute():
        base = REPO / base
    return base / incident_id / report_id


def start_report(incident_id: str, package_md: str, *, out_root: str | None = None,
                 timeout_s: int = 1800, cwd: str | None = None,
                 confirm_spawn: bool = False) -> dict:
    """**启动**一次 headless DSH 分析（非阻塞）；返回 report_id 与留痕路径。

    ⚠️ `confirm_spawn=True` 是**必须显式给的**（默认拒绝）。理由是一次实测事故：
    2026-09-30 我写了个"冒烟测试"，以为只是组装 prompt，结果它**真的把 headless DSH 拉起来了**
    —— 它启动、读 prompt、开始推理、消耗 token，我才发现。凡是"会真的花钱/真的动起来"的动作，
    调用点必须写明意图，不能靠"我以为是干跑"。

    另外：`PYTEST_CURRENT_TEST` 下**只允许** `DSH_BIN` 指定的替身 —— 测试绝不许跑真 DSH。

    调用方（控制台）另外负责两件事，本模块**不重复实现**（免得出现第二个口径来源）：
    ① **模式门禁**：离线模式不许上报（模式是控制台的状态）；② **去重**：同一条失败不并行重复跑。
    """
    if not confirm_spawn:
        return {"error": "拒绝启动：这是一次真实的 headless DSH 运行（会消耗 token）。"
                         "调用方必须显式传 confirm_spawn=True。",
                "blocked_by": "confirm_spawn_required"}
    under_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if under_test and not (os.environ.get("DSH_BIN") or "").strip():
        return {"error": "测试期拒绝启动真实 headless DSH：必须用 DSH_BIN 指定一个替身脚本。",
                "blocked_by": "pytest_requires_fake_dsh"}
    argv_pre, how = find_dsh()
    if argv_pre is None:
        return {"error": how, "hint": "设 DSH_BIN 后重试；本模块不猜 dsh 的位置"}
    rid = new_report_id()
    log_target = report_log()          # ★ 这一次上报固定用这一个台账（见 `_PROCS` 的注释）
    d = report_root(incident_id, rid, out_root)
    d.mkdir(parents=True, exist_ok=True)
    prompt_path = d / "prompt.md"
    prompt = build_prompt(incident_id, package_md, prompt_path=prompt_path)
    with prompt_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(prompt)
    # argv 里只放**指路**：整包 markdown 塞 argv 会超长，且会把引号问题引进来
    task = ("读取 %s 并严格按其中的要求完成分析（只读，不要修改任何仓库文件）。"
            % str(prompt_path).replace("\\", "/"))
    cmd = [*argv_pre, "--profile", "headless", task]
    stdout_path = d / "stdout.txt"
    try:
        fh_out = stdout_path.open("wb")
        proc = subprocess.Popen(cmd, stdout=fh_out, stderr=subprocess.STDOUT,
                                cwd=str(cwd or REPO), stdin=subprocess.DEVNULL)
    except OSError as exc:
        return {"error": "无法启动 headless DSH：%s" % exc, "cmd": cmd}
    meta = {"report_id": rid, "incident_id": incident_id, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "running", "pid": proc.pid, "how": how, "mode": "readonly",
            "timeout_s": timeout_s, "dir": _rel(d), "cmd": _display_cmd(cmd),
            "prompt_path": _rel(prompt_path), "stdout_path": _rel(stdout_path)}
    _append(meta, log_target)
    # 进程句柄 + **当时那个台账路径**都留着给 `finish_report`：
    # 交给调用方再传回来会绕一大圈，而"用 tasklist 轮询 PID 假装 wait()"不可靠。
    with _PROC_LOCK:
        _PROCS[rid] = {"proc": proc, "log": log_target}
    return {"report_id": rid, "status": "running", "pid": proc.pid, "dir": _rel(d),
            "prompt_path": _rel(prompt_path), "stdout_path": _rel(stdout_path),
            "how": how, "cmd": _display_cmd(cmd), "timeout_s": timeout_s,
            "note": "已在后台启动 headless DSH（只读分析）。结果会写进 stdout.txt 与台账。"}


def _display_cmd(cmd: list[str]) -> str:
    """给人看的命令（**不**含完整任务文本，那里面是整包内容）。"""
    return " ".join(cmd[:4] + ["<任务：读 prompt.md 并只读分析>"])


def finish_report(report_id: str, *, timeout_s: int = 1800) -> dict:
    """等它结束（由后台线程调用）；超时则**杀进程树**并如实标 timeout。"""
    with _PROC_LOCK:
        held = _PROCS.pop(report_id, None)
    t0 = time.time()
    if held is None:
        return {"report_id": report_id, "status": "unknown",
                "error": "找不到该上报的进程句柄（控制台可能重启过）⇒ **终态未知**，不猜成功或失败",
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    proc = held["proc"]
    log_target = pathlib.Path(held["log"])     # ★ 用**启动时**那个台账，不重读 env
    timed_out = False
    try:
        code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc.pid)
        try:
            code = proc.wait(timeout=30)
        except Exception:
            code = None
    dur = round(time.time() - t0, 2)
    rec = _merged(log_target)
    mine = next((r for r in rec if r.get("report_id") == report_id), None) or {}
    d = REPO / str(mine.get("dir") or "")
    stdout_txt, tail = "", ""
    sp = d / "stdout.txt"
    if sp.is_file():
        stdout_txt = sp.read_text(encoding="utf-8", errors="replace")
        tail = stdout_txt[-4000:]
    analysis = d / "analysis.md"
    status = "timeout" if timed_out else ("done" if code == 0 else "failed")
    upd = {"report_id": report_id, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "status": status, "exit_code": code, "duration_s": dur,
           "stdout_bytes": len(stdout_txt.encode("utf-8")),
           "tail": tail, "analysis_path": _rel(analysis) if analysis.is_file() else None}
    _append(upd, log_target)
    return upd


def _kill_tree(pid: int) -> dict:
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True)
        return {"method": "taskkill /T /F", "rc": r.returncode}
    try:
        os.kill(pid, 9)
        return {"method": "SIGKILL", "rc": 0}
    except Exception as exc:
        return {"method": "SIGKILL", "error": str(exc)}


def _append(rec: dict, target: pathlib.Path | None = None) -> None:
    target = target or report_log()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def report_log() -> pathlib.Path:
    """台账路径：env 覆盖 > 测试期临时文件 > 生产（沿用失败通道的三级优先）。"""
    env = os.environ.get("MEMS_DSH_REPORT_LOG")
    if env:
        return pathlib.Path(env)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return pathlib.Path(tempfile.gettempdir()) / "memshop-dsh-reports-under-test.jsonl"
    return REPORT_LOG


def _merged(p: pathlib.Path) -> list[dict]:
    """按 report_id 归并「启动/结束」两条记录（同一台账 append-only）。"""
    merged: dict[str, dict] = {}
    order: list[str] = []
    if p.is_file():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            rid = str(r.get("report_id") or "")
            if not rid:
                continue
            if rid not in merged:
                merged[rid] = {}
                order.append(rid)
            merged[rid].update(r)
    return [merged[r] for r in order][::-1]


def load_reports(incident_id: str | None = None, limit: int = 50) -> dict:
    p = report_log()
    n_bad = 0
    if p.is_file():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not ln.strip():
                continue
            try:
                if not str(json.loads(ln).get("report_id") or ""):
                    n_bad += 1
            except ValueError:
                n_bad += 1
    items = _merged(p)
    if incident_id:
        items = [r for r in items if r.get("incident_id") == incident_id]
    return {"n_total": len(items), "n_bad_lines": n_bad, "items": items[:max(1, limit)],
            "log": _rel(p)}


def running(incident_id: str) -> dict | None:
    for r in load_reports(incident_id=incident_id, limit=50)["items"]:
        if r.get("status") == "running":
            return r
    return None


def _rel(p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(p)
