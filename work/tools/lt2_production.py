"""LT2 生产 runner：外层 supervisor + 每组合作业进程（含运行期 watchdog）。

授权口径（Codex 2026-09-14 裁定）
--------------------------------
- `server_lifecycle_size = 1`：**每个组合一个全新 server**，严格串行；
- 逻辑批大小 4 → 6 → max 8，**禁止 12–16**；
- 频率 5/10/15/20/25/30/35 MHz，每组合 7 点；
- 驱动 = 反相电压（pot1=+1V / pot2=−1V / gnd1=0V，term1、cir 停用）；
- **必须先有运行期实时中止机制**——由 `work/tools/lt2_sampler.py` 在采样循环内判定，
  本文件在秒级轮询并动作。

为什么是三个进程（实测约束，不是设计偏好）
------------------------------------------
实测已知约束：**MPh 一个 Python 会话只能有一个 `mph.Client`**（`disconnect()` 后再
`mph.Client()` 会报 `Not connected to a server`）。而授权要求「每个组合一个全新 server」。
两者无法在单进程内同时满足，故架构为：

    supervisor（本文件 --role supervisor，不 import mph，只做编排与核验）
      └─ combo-worker（本文件 --role combo-worker，每次一个全新进程 → 一个全新 client/server）
           └─ sampler（lt2_sampler.py，独立 sidecar，运行期实时判定）

取消路径的归属
--------------
求解期主线程阻塞在 `study.run()`，无法轮询；因此由 **worker 进程内的 watchdog 线程**执行取消：
先优雅取消（`client.clear()`/`disconnect()`），失败才终止 server——且终止前必须通过
PID + 启动时间 + 端口归属（`port_owner_ok`）三重核验。supervisor 只在 worker 失联时升级处置，
同样必须通过核验；核验不过**拒绝终止并如实记录**。

用法
----
预检（只读探测，不启动 COMSOL）：
    python work/tools/lt2_production.py --run-id lt2-prod-b2-r1 --preflight-only
干跑（模拟样本驱动门禁与状态机，不启动 COMSOL）：
    python work/tools/lt2_production.py --run-id lt2-prod-b2-r1 --dry-run
真实生产（**需要放宽文件策略 + 明确授权**）：
    python work/tools/lt2_production.py --run-id lt2-prod-b2-r1
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rt_gate import (  # noqa: E402  纯逻辑门禁，复用不重写
    GateEngine,
    Thresholds,
    atomic_write_json,
    port_owner_ok,
    read_json_safe,
    sidecar_health,
)

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
# 运行根可被**显式**覆盖（Codex R6 §3.2 方案 A：唯一运行根 / test namespace）。
# 动机：验收进程必须各写独立目录，否则两个进程互删共享目录（实测 3/14 flake、根因=跨进程目录冲突）。
# 注意：被测路径由本模块的全局 RUNS 决定，因此"每个进程一个唯一根"必须在这里可注入，
# 否则测试侧无论怎么隔离都无效（实测：测试在 namespace 建目录，而 worker 仍写共享根 ⇒ 8 项失败）。
# fail-closed：覆盖值必须是**绝对路径**，否则拒绝启动（不允许相对路径歧义）。
_RUNS_ENV = os.environ.get("LT2_RUNS_ROOT")
if _RUNS_ENV:
    _runs_override = Path(_RUNS_ENV)
    if not _runs_override.is_absolute():
        raise SystemExit(f"[STOP] LT2_RUNS_ROOT 必须是绝对路径：{_RUNS_ENV!r}")
    RUNS = _runs_override
    RUNS_ROOT_SOURCE = "env:LT2_RUNS_ROOT"
else:
    RUNS = REPO / "work" / "runs"
    RUNS_ROOT_SOURCE = "default:work/runs"
MODELS = REPO / "work" / "models"
MODEL = MODELS / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
SIDECAR = Path(__file__).resolve().parent / "lt2_sampler.py"
SELF = Path(__file__).resolve()

PORT = 2036
FIXED_CLOCK_ISO = "2026-09-14T04:00:00"   # 确定性模式的固定时间戳（与 sampler 的基准同源）
DEFAULT_FREQS = ("5", "10", "15", "20", "25", "30", "35")
DEFAULT_COMBOS = ((0.6, 4), (0.7, 5), (0.45, 6), (0.75, 5))
SERVER_LIFECYCLE_SIZE = 1
ALLOWED_BATCH_SIZES = (4, 6, 8)
FORBIDDEN_BATCH_SIZES = (12, 13, 14, 15, 16)
DRIVE_MODE = "dual_electrode_antiphase_voltage_drive"

# 前置门禁（父 agent 2026-09-14 裁定：**统一采用 18,000 / 21,500**，取代原 16,384/16,384）
# 依据（实测 r3e）：启动时 avail 18,754 / commit 24,347（**已高于**旧门禁 16,384），
# 仍在 5 秒内被外部消费者吃掉约 6 GB commit（commit 掉到 **0.5 MB**）⇒ 旧门禁不足以保证平台期安全。
# 覆盖仍可走 CLI（--avail-gate/--commit-gate），但**覆盖值必须写入产物**（见 preflight 的 gates/gate_overridden）。
PREFLIGHT_AVAIL_MB = 18000.0
PREFLIGHT_COMMIT_MB = 21500.0
# 开跑前**连测两次**（外部消费者可在数秒内阶跃占用；单次采样不足以证明"开跑时环境干净"）。
PREFLIGHT_DOUBLE_SAMPLE_GAP_S = 5.0
# 前置门禁的**进程**检查：以下 COMSOL 家族进程在场即**拒绝启动**（避免带着未登记变量做验证）。
COMSOL_BLOCKING_PROCS = ("comsolmphserver", "comsolbatch", "comsolcompile")
# 用户 GUI：在场**允许**（不得据此拒绝启动），但必须记录并在报告中声明。
COMSOL_GUI_ALLOWED = ("ComsolUI",)
ATTENDED_OPERATION = True   # §3.3：未调页面文件时只允许有人值守、单组合一 server

GATE_POLL_S = 2.5          # supervisor / watchdog 轮询周期
HARD_STOP_GRACE_S = 15     # 硬线后请求 worker 正常结束的宽限期（§7.1）
ENFORCE_WORKER_WAIT_S = 5  # enforce 之后为记录**真实** worker 退出码而做的有界等待（不参与判定）
NORMAL_COMPLETION_GRACE_S = 60.0  # 正常收尾守卫：等 worker 自然退出的上界；超过即升级处置
                                  # （持续抑制 enforce 必须封顶，否则 worker 卡死会永久阻塞 supervisor）
# 假 worker 宣告 stage=closed 之后的**显式驻留**（仅确定性自测/固定时间戳模式生效）。
# 理由（父 agent 2026-09-15 裁定 A）：真 worker 收尾还要拆 sampler / COMSOL server，
# supervisor 总能观测到"已宣告收尾但进程仍在"的窗口（r3f 的生产 child 目录确实留下了
# 正常收尾记录）；而旧假 worker 写完 closed 就立刻 return ⇒ 该窗口退化为**微秒级竞态**
# ⇒ "写不写正常收尾记录"随机 ⇒ T14 逐字节断言在**同一份代码**上摇摆（实测 81/82 vs 82/82）。
# 显式驻留使测试替身与真 worker 的收尾时序一致 ⇒ 断言重新变成确定性的。
FAKE_CLOSED_LINGER_S = 1.5
WORKER_RECLAIM_AFTER_S = 20  # 宽限期后 worker 仍存活 → 回收 worker 进程
PORT_CLOSE_WAIT_S = 30
# 启动宽限：worker 导入 numpy/mph 需要时间；在此期间"还没有 sampler_pid / 还没有样本"
# **不得**判为 sidecar 失效（D-A 的根因就是首轮就误判 sidecar_exited 并立即终止）。
STARTUP_GRACE_S = 180.0
AREA_REL_TOL = 1e-6        # §5 批准，**仅限**冻结控制面重建一致性门禁
BBOX_REL_TOL = 1e-6
TOLERANCE_SCOPE = ("frozen Ptot control-surface reconstruction consistency gate "
                   "（不得用于声称与解析几何一致；2πR² 的 0.271% 是另一个问题）")

# child / attempt 证据隔离目录（§7.2）
# **唯一规则**：`child_*/` 只放证据；supervisor 的跨进程信号放在 `<run_id>/signals/`。
# （D-A：把 signal 写进 child 目录会与 worker 的「非空即拒绝」守卫互斥，worker 永远起不来。）
CHILD_DIR_FMT = "child_{idx:02d}_attempt_{attempt}"
SIGNAL_DIR_NAME = "signals"
WORKER_STATE_NAME = "worker_state.json"
SAMPLER_STATE_NAME = "sampler_state.json"
TRIGGER_FILE_NAME = "termination_trigger.json"
# **正常收尾**记录**不得**再用"终止触发"之名（父 agent 2026-09-15 裁定 B）：
# 一次根本没发生终止的运行里存在 termination_trigger.json，本身就是"名字与语义不一致"
# （与 pass_conditions 里混计数器、`..._equal=false` 同一族）。文件内容本就写着
# trigger_kind=normal_completion_sidecar_exit / is_hard_stop=false / enforced=false，
# 现在文件名与之一致。**判据**：只有 TRIGGER_FILE_NAME 才表示"有终止动作记录"。
COMPLETION_FILE_NAME = "completion_record.json"
REFUSED_FILE_SUFFIX = "_refused.json"
# 控制通道文件：哈希不得进入聚合证据（见 describe_child_dir）
CONTROL_CHANNEL_FILES = ("worker_state.json",)


def signal_path(run_id: str, child_dir_name: str) -> Path:
    return RUNS / run_id / SIGNAL_DIR_NAME / f"{child_dir_name}.signal.json"


_fixed_clock = lambda: FIXED_CLOCK_ISO  # noqa: E731

# ---- 演练（drill）：仅用于 U1/U2/U3 真机验证，绝不可用于生产 ----
DRILL_NOTE = ("演练阈值覆盖：本次硬停**不是**真实资源越线，"
              "禁止把本 run 的任何产物当作生产资源事件或用于资源放行判断")
DRILL_THRESHOLD_ARGS = ("ws_hard_stop_mb", "commit_hard_stop_mb", "physical_hard_stop_mb")


def resolve_thresholds(args) -> tuple[Thresholds, dict]:
    """**唯一**的阈值裁定点：默认值 = Codex 裁定值；覆盖只在 `--drill` 下允许。

    CLI 层负责拒绝「无 --drill 却传阈值覆盖」；本函数负责应用并留痕。
    """
    th = Thresholds()
    rec = {"drill": bool(getattr(args, "drill", False)),
           "defaults": th.to_dict(), "overrides": {}}
    if not rec["drill"]:
        rec["effective"] = th.to_dict()
        return th, rec
    for k in DRILL_THRESHOLD_ARGS:
        v = getattr(args, k, None)
        if v is not None:
            rec["overrides"][k] = {"default": getattr(th, k), "drill_value": float(v)}
            setattr(th, k, float(v))
    rec["effective"] = th.to_dict()
    rec["note"] = DRILL_NOTE
    return th, rec

# ⚠️ 只读**输入**（判据哈希、冻结控制面签名）必须锚定到仓库固定的 work/runs，
# **不能**跟着可覆盖的 RUNS 走：它们是既有证据，不是本次运行的产物。
# 实测：把 RUNS 指到 namespace 后，这两个路径变成 namespace 内不存在的文件 ⇒ 收尾阶段
# `FileNotFoundError`（T17 复现）。输出/输入必须分开。
RUNS_INPUTS = REPO / "work" / "runs"
CRITERIA_SUMMARY = RUNS_INPUTS / "lt1-reverse-sample" / "lt1_validation_summary_v2.json"
FROZEN_PRECHECK = (RUNS_INPUTS / "precheck-b2-phase2-v5-aggregate"
                   / "geometry_selection_precheck.json")

DEVNULL = subprocess.DEVNULL


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def sysmem() -> dict:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"system_available_physical_mb": round(m.ullAvailPhys / 1048576, 1),
            "system_memory_load_percent": int(m.dwMemoryLoad),
            "commit_available_mb": round(m.ullAvailPageFile / 1048576, 1)}


def procmem(pid: int | None) -> dict:
    if not pid:
        return {}
    h = ctypes.windll.kernel32.OpenProcess(0x0410, False, int(pid))
    if not h:
        return {}
    try:
        c = PMC()
        c.cb = ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        return {"server_working_set_mb": round(c.WorkingSetSize / 1048576, 1),
                "server_peak_working_set_mb": round(c.PeakWorkingSetSize / 1048576, 1)}
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def proc_exists(pid: int | None) -> bool:
    """进程是否仍在**运行**（不是"句柄还能不能打开"）。

    ⚠️ 实测坑（本文件在故障注入测试中踩到并修正）：
    Windows 上进程被终止后，只要父进程（`subprocess.Popen`）**仍持有进程句柄**，
    `OpenProcess` 依然会成功返回句柄，因此"能否 OpenProcess"永远为真，
    会把成功的终止误判成"进程仍在"。正确判据是
    `GetExitCodeProcess(...) == STILL_ACTIVE(259)`。
    """
    if not pid:
        return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wt.DWORD(0)
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        if not ok:
            return False
        return int(code.value) == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# ③ `--freqs` 解析加固（父 agent 2026-09-14 分派）
# --------------------------------------------------------------------------- #
# 触发事实（父 agent 实测）：命令里写 `--freqs '5 10 15 20 25 30 35'`（**空格**分隔），
# 而旧实现只按逗号切分 ⇒ 字面执行只得 **1 个**频率：**不报错，但事实已变**。
# 这正是本项目一路在打的「静默失败」类缺陷，故此处按 fail-closed 处理：
#   a) 同时接受逗号（含全角）与空白分隔；
#   b) 解析结果（`parsed_freq_list_MHz` + count）**写入产物**，使任何误解析可见；
#   c) 结果为空 / 含重复 / 含非法 token / 数量与期望不符 ⇒ **拒绝启动**并给非零退出码。
FREQ_SEPARATORS_ACCEPTED = ("半角逗号 ','", "全角逗号 '，'", "空白（空格 / 制表 / 换行）")
# 「期望数量」的来源（父 agent 要求写明）：默认 = 本模块声明的**生产授权口径**
# （`len(DEFAULT_FREQS)` = 7 点/组合，5..35 MHz，Codex 裁定）；如需非生产点数，
# 必须用 `--expect-freq-count N` **显式**覆盖，覆盖值同样写入产物。
EXPECTED_FREQ_COUNT = len(DEFAULT_FREQS)
FREQ_PARSE_REFUSAL_EXIT = 10   # --freqs 解析 fail-closed 拒绝启动
FREEZE_UNRESOLVED_EXIT = 11    # --freeze-id 给了但核验无法完成/不通过


def parse_freqs(raw, expect_count: int | None = None) -> tuple[tuple[str, ...], dict]:
    """解析 `--freqs` 并返回 `(tokens, record)`；`record["ok"]` 为 False 时调用方必须拒绝启动。

    切分规则：先把全角逗号归一为半角，再按 `[,\\s]+` 切分 ⇒ 空格分隔与逗号分隔**等价**。
    重复判定按**数值**（`float` 规范化）而非字面 token：`5` 与 `5.0` 视为同一频率重复
    （否则会出现两行同一频率，仍属静默变形）。非法判定 = 不能解析为**有限正浮点数**。
    """
    raw_s = "" if raw is None else str(raw)
    if expect_count is None:
        expect = int(EXPECTED_FREQ_COUNT)
        expect_src = (f"默认生产授权口径 EXPECTED_FREQ_COUNT={EXPECTED_FREQ_COUNT}"
                      f"（= len(DEFAULT_FREQS)）")
    else:
        expect = int(expect_count)
        expect_src = f"CLI 显式 --expect-freq-count={expect}"
    tokens = [t for t in re.split(r"[,\s]+", raw_s.replace("，", ",").strip()) if t]

    values: list[float] = []
    invalid: list[str] = []
    for t in tokens:
        try:
            v = float(t)
        except Exception:  # noqa: BLE001
            invalid.append(t)
            continue
        if not math.isfinite(v) or v <= 0:
            invalid.append(t)
            continue
        values.append(v)

    seen: dict[str, str] = {}
    dup: list[dict] = []
    for t in tokens:
        try:
            key = repr(float(t))
        except Exception:  # noqa: BLE001
            key = t
        if key in seen:
            dup.append({"value": key, "tokens": [seen[key], t]})
        else:
            seen[key] = t

    problems: list[str] = []
    if not tokens:
        problems.append("解析结果为空（raw 中没有可识别的频率 token）")
    if invalid:
        problems.append(f"非法 token（须为有限正浮点数）：{invalid}")
    if dup:
        problems.append(f"重复频率：{[d['value'] for d in dup]}")
    if len(tokens) != expect:
        problems.append(f"数量不符：解析得 {len(tokens)} 个，期望 {expect} 个")

    rec = {
        "raw": raw_s,
        "separators_accepted": list(FREQ_SEPARATORS_ACCEPTED),
        "split_regex": r"[,\s]+（全角逗号先归一为半角）",
        "tokens": tokens,
        "token_count": len(tokens),
        "parsed_freq_list_MHz": values,
        "parsed_freq_list_MHz_count": len(values),
        "duplicate_freq_values": [d["value"] for d in dup],
        "duplicate_tokens": dup,
        "invalid_tokens": invalid,
        "expected_count": expect,
        "expected_count_source": expect_src,
        "count_matches_expected": len(tokens) == expect,
        "canonical_plist": " ".join(f"{t}[MHz]" for t in tokens),
        "canonical_tokens_joined": ",".join(tokens),
        "ok": not problems,
        "problems": problems,
    }
    return tuple(tokens), rec


# --------------------------------------------------------------------------- #
# ② 冻结核验证据（父 agent 2026-09-14 分派）
# --------------------------------------------------------------------------- #
# 要求：`batch_manifest.json` 必须写入 `freeze_id`、**运行时**前后两次冻结核验结果与时间戳、
# 以及 `freeze_hash_pre_post_match`（布尔，前后一致才 true）。动机：冻结前后哈希比对是
# Codex 明确要求的证据项；缺它就无法从**运行自身的产物**证明「运行期间冻结未漂移」
# （靠事后手工 `--verify` 是审阅方的动作，不是被审运行的记录）。
FREEZE_GROUPS = ("targets", "dependencies", "acceptance_aux")
FREEZE_DIR_FMT = "lt2-supervisor-acceptance-{freeze_id}"
FREEZE_VERIFIER = ("lt2_production.freeze_verify（只读；口径同 work/tools/freeze_snapshot.py "
                   "--verify：source-vs-manifest，三个分组全查）")


def freeze_dir(freeze_id: str) -> Path:
    return RUNS / FREEZE_DIR_FMT.format(freeze_id=freeze_id)


def _files_digest(files: list[dict]) -> str | None:
    try:
        blob = json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def freeze_verify(freeze_id: str, fixed_at: str | None = None) -> dict:
    """只读执行一次「冻结哈希核验」：把 `freeze_manifest.json` 登记的文件与**当前**源文件比对。

    **只读**：不写任何文件、不改状态（因此可以安全地在运行前后各执行一次）。
    不 import `freeze_snapshot.py`——它是冻结窗口的守护者，不应成为被测运行期的依赖。
    """
    mp = freeze_dir(freeze_id) / "freeze_manifest.json"
    rec: dict = {"freeze_id": freeze_id, "at": fixed_at or now_iso(),
                 "clock_mode": "fixed" if fixed_at else "wallclock",
                 "manifest_path": str(mp), "manifest_present": mp.is_file(),
                 "mode": "source-vs-manifest", "groups": list(FREEZE_GROUPS), "read_only": True}
    if not mp.is_file():
        rec.update({"ok": False, "verdict": "MANIFEST_NOT_FOUND", "drift_count": None,
                    "drift": [], "frozen_file_count": 0, "files": [], "files_digest": None,
                    "problem": f"找不到冻结清单：{mp}"})
        return rec
    try:
        man = json.loads(mp.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        rec.update({"ok": False, "verdict": "MANIFEST_UNREADABLE", "drift_count": None,
                    "drift": [], "frozen_file_count": 0, "files": [], "files_digest": None,
                    "problem": f"{type(exc).__name__}: {exc}"})
        return rec

    files: list[dict] = []
    drift: list[dict] = []
    for group in FREEZE_GROUPS:
        for e in (man.get(group) or []):
            p = Path(str(e.get("path", "")))
            exists = p.is_file()
            cur = sha256_file(p) if exists else None
            files.append({"group": group, "file": p.name, "path": str(p), "exists": exists,
                          "frozen_sha256": e.get("sha256"), "current_sha256": cur})
            if cur != e.get("sha256"):
                drift.append({"group": group, "file": p.name,
                              "frozen": e.get("sha256"), "current": cur})
    rec.update({
        "ok": not drift,
        "verdict": "MATCH" if not drift else "INVALIDATED_BY_CODE_DRIFT",
        "freeze_status": man.get("status"),
        "freeze_manifest_sha256": sha256_file(mp),
        "frozen_file_count": len(files),
        "files": files,
        "files_digest": _files_digest(files),
        "drift": drift,
        "drift_count": len(drift),
        "problem": None if not drift else f"{len(drift)} 个文件与冻结值不一致",
    })
    return rec


# 父 agent 2026-09-14 裁定 2：**拆成三个各自只有一个含义的布尔**
# （此前把一个多义布尔命名为 freeze_hash_pre_post_match，是「命名把两个含义塞进一个字段」
#   的第 3 个同类教训；功能正确但语义不清 ⇒ 拆开，判定逻辑与阈值不变。）
FREEZE_TRIO_DEFINITION = (
    "三个布尔各自只有一个含义："
    "freeze_hash_pre_post_match = (运行前核验 ok) AND (运行后核验 ok) "
    "AND (两次逐文件哈希集合完全一致) —— 只回答「冻结哈希前后是否对得上」；"
    "executed_from_frozen_snapshot = (运行中的脚本逐字节 == 冻结件) —— 只回答「是否从冻结副本执行」；"
    "freeze_evidence_complete = 前两者皆 true —— 只回答「本次运行的冻结证据是否完整可用」。")


def freeze_evidence(freeze_id: str | None, pre: dict | None, post: dict | None,
                    script_sha256: str | None) -> dict:
    """把运行前/后两次核验拼成**自解释**的产物字段（②；裁定 2 的三布尔拆分）。"""
    if not freeze_id:
        return {
            "requested": False, "freeze_id": None, "verifier": FREEZE_VERIFIER,
            "reason": ("未提供 --freeze-id ⇒ 本次运行**没有冻结证据**：运行自身无法证明冻结未漂移，"
                       "也无法证明跑的是冻结件。补齐方式：启动时加 "
                       "`--freeze-id <freeze_id>`（例如 "
                       "`--freeze-id freeze-20260914-1940-post-freqs-freeze-evidence`）；"
                       "该 id 须已由 `python work/tools/freeze_snapshot.py --create` 建立，"
                       "且 `python work/tools/freeze_snapshot.py --verify <freeze_id>` 为 MATCH。"
                       "在补齐之前，以下三个布尔一律 false（fail-closed），检查器必须判失败。"),
            "pre": None, "post": None,
            "pre_verdict": None, "post_verdict": None,
            "pre_drift_count": None, "post_drift_count": None,
            "pre_post_files_identical": False,
            "running_script_is_frozen_target": None,
            "freeze_hash_pre_post_match": False,
            "executed_from_frozen_snapshot": False,
            "freeze_evidence_complete": False,
            "definition": FREEZE_TRIO_DEFINITION,
        }
    both_ok = bool(pre and post and pre.get("ok") and post.get("ok"))
    identical = bool(both_ok and pre.get("files_digest")
                     and pre.get("files_digest") == post.get("files_digest"))
    frozen_self = None
    for f in ((pre or {}).get("files") or []):
        if f.get("file") == SELF.name:
            frozen_self = f
            break
    running_ok = bool(frozen_self and script_sha256
                      and frozen_self.get("frozen_sha256") == script_sha256)
    hash_match = bool(identical)               # 只回答「哈希前后对不对得上」
    executed = bool(running_ok)                # 只回答「是否从冻结副本执行」
    return {
        "requested": True, "freeze_id": freeze_id, "verifier": FREEZE_VERIFIER,
        "manifest_path": (pre or {}).get("manifest_path"),
        "freeze_manifest_sha256": (pre or {}).get("freeze_manifest_sha256"),
        "mode": ("source-vs-manifest（targets / dependencies / acceptance_aux 三个分组全查）；"
                 "pre = 批次开始前，post = 批次结束后"),
        "pre": pre, "post": post,
        "pre_verdict": (pre or {}).get("verdict"), "post_verdict": (post or {}).get("verdict"),
        "pre_drift_count": (pre or {}).get("drift_count"),
        "post_drift_count": (post or {}).get("drift_count"),
        # 分量（细节，不是放行判据）：两次文件集合是否逐字节相同
        "pre_post_files_identical": identical,
        "running_script_is_frozen_target": {
            "file": SELF.name, "self_path": str(SELF), "self_sha256": script_sha256,
            "frozen_target_sha256": (frozen_self or {}).get("frozen_sha256"),
            "match": executed,
            "note": "运行中的 lt2_production.py 是否与冻结值逐字节一致（防从非冻结副本执行）"},
        "freeze_hash_pre_post_match": hash_match,
        "executed_from_frozen_snapshot": executed,
        "freeze_evidence_complete": bool(hash_match and executed),
        "definition": FREEZE_TRIO_DEFINITION,
    }


def run_ps(script: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def find_pid() -> int | None:
    out = run_ps("(Get-Process comsolmphserver -ErrorAction SilentlyContinue | "
                 "Sort-Object StartTime -Descending | Select-Object -First 1).Id")
    return int(out) if out.isdigit() else None


def proc_identity(pid: int | None) -> dict | None:
    """进程身份指纹：PID + 启动时间（FileTime）+ 进程名 + 父进程 PID。

    启动时间用于区分「同一 PID 被复用」；父进程用于记录 server 与 worker 的父子关系（§7.4）。
    """
    if not pid:
        return None
    out = run_ps(f"$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
                 "if($p){ $pp=(Get-CimInstance Win32_Process -Filter \"ProcessId=$($p.Id)\" "
                 "-ErrorAction SilentlyContinue).ParentProcessId; "
                 "\"$($p.Id)|$($p.StartTime.ToFileTime())|$($p.ProcessName)|$pp\" }")
    if not out:
        return None
    parts = out.split("|")
    if len(parts) != 4:
        return None
    return {"pid": int(parts[0]), "start_filetime": parts[1], "name": parts[2],
            "parent_pid": int(parts[3]) if parts[3].strip().isdigit() else None}


def port_open(p: int = PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", p), timeout=1.5):
            return True
    except OSError:
        return False


def port_owner_pid(p: int = PORT) -> int | None:
    out = run_ps(f"(Get-NetTCPConnection -LocalPort {int(p)} -State Listen "
                 "-ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess")
    if out.isdigit():
        return int(out)
    out = run_ps(f"netstat -ano | Select-String ':{int(p)}\\s' | Select-Object -First 1")
    for tok in reversed(out.split()):
        if tok.isdigit():
            return int(tok)
    return None


def server_pid_from_port(timeout_s: float = 30.0) -> dict:
    """**优先**用监听端口直接取 server PID（§7.4），而不是 `find_pid()` 启发式。

    返回 `{"pid":…, "source":"port_owner"|"find_pid_fallback"|"none", "waited_s":…}`。
    """
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        owner = port_owner_pid(PORT)
        if owner:
            return {"pid": owner, "source": "port_owner",
                    "waited_s": round(time.time() - t0, 1)}
        time.sleep(1)
    fb = find_pid()
    if fb:
        return {"pid": fb, "source": "find_pid_fallback",
                "waited_s": round(time.time() - t0, 1),
                "note": "端口在超时内未监听，回退到启发式（须在产物中标注）"}
    return {"pid": None, "source": "none", "waited_s": round(time.time() - t0, 1)}


def list_comsolmphserver() -> list[int]:
    out = run_ps("(Get-Process comsolmphserver -ErrorAction SilentlyContinue | "
                 "Select-Object -ExpandProperty Id) -join ','")
    return [int(x) for x in out.split(",") if x.strip().isdigit()]


def _wait_until(pred, timeout_s: float = 15.0, step_s: float = 0.5) -> dict:
    """轮询等待某个条件成立（终止后 PID/端口的消失**需要时间**，不能只查一次）。

    这是本文件在故障注入测试中暴露出的真实缺陷：`Stop-Process` 返回 rc=0 之后，
    进程对象仍会短暂存在，立即查 `OpenProcess` 会得到"仍存在"，从而把成功的终止误判为失败。
    """
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return {"ok": True, "waited_s": round(time.time() - t0, 1)}
        time.sleep(step_s)
    return {"ok": bool(pred()), "waited_s": round(time.time() - t0, 1), "timed_out": True}


def verify_termination(pid: int | None, cmd_rc: int | None, port: int = PORT,
                       wait_pid_s: float = 15.0, wait_port_s: float = 10.0) -> dict:
    """终止后的**二次确认**（§7.4）：不能只因为调用了 Stop-Process 就记为成功。

    四项都必须确认：终止命令退出码、expected PID 消失、端口关闭、没有意外的 comsolmphserver。
    PID 与端口都用**带超时的轮询**确认（进程退出不是瞬时的）。
    """
    pid_wait = _wait_until(lambda: not proc_exists(pid), timeout_s=wait_pid_s) if pid \
        else {"ok": True, "waited_s": 0.0, "note": "expected_pid 为空，无法确认"}
    port_wait = _wait_until(lambda: not port_open(port), timeout_s=wait_port_s)
    remaining = list_comsolmphserver()
    expected = int(pid) if pid else None
    unexpected = [p for p in remaining if p != expected]
    checks = {
        "termination_command_exit": cmd_rc,
        "expected_pid_absent": (not proc_exists(pid)) if pid else None,
        "expected_pid_absent_wait": pid_wait,
        "port_closed": not port_open(port),
        "port_closed_wait": port_wait,
        "no_new_unexpected_comsolmphserver": (len(unexpected) == 0),
        "remaining_comsolmphserver_pids": remaining,
        "unexpected_comsolmphserver_pids": unexpected,
    }
    checks["verified"] = bool(
        (checks["expected_pid_absent"] is True)
        and checks["port_closed"] is True
        and checks["no_new_unexpected_comsolmphserver"] is True
        and (cmd_rc is None or cmd_rc == 0))
    return checks


# --------------------------------------------------------------------------- #
# 状态文件：**每个文件单写者**（§7.3 的修复方式）
#
#   worker_state.json      —— 只有 combo-worker 写
#   sampler_state.json     —— 只有 sidecar 写
#   supervisor_signal.json —— 只有 supervisor 写
#
# v1 让 worker 与 sidecar 都「读整个 JSON → 改 → 原子替换」同一个文件，
# 那是跨进程读-改-写竞争：原子替换只防止半写文件，**不能**防止基于旧版本互相覆盖。
# 拆成三个单写者文件后，该竞争从结构上不存在。
# --------------------------------------------------------------------------- #
def write_own_state(path: Path, payload: dict) -> dict:
    """单写者写入：调用方必须是该文件的唯一写入者。写失败抛异常（不静默）。

    `updated_at` 用 `setdefault`：调用方显式给定时保留（确定性/证据复算模式需要），
    否则填当前墙钟。
    """
    payload = dict(payload)
    payload["writer"] = payload.get("writer") or "unknown"
    payload.setdefault("updated_at", now_iso())
    r = atomic_write_json(path, payload)
    if not r.get("ok"):
        raise RuntimeError(f"{path.name} 原子写失败: {r.get('error')}")
    return payload


def read_worker_state(child_dir: Path) -> dict:
    return read_json_safe(child_dir / WORKER_STATE_NAME)


def read_sampler_state(child_dir: Path) -> dict:
    return read_json_safe(child_dir / SAMPLER_STATE_NAME)


def read_supervisor_signal(run_id: str, child_dir_name: str) -> dict:
    """读 supervisor 的结束请求。

    D-D 排查发现：本函数曾是 `child_dir / SUPERVISOR_SIGNAL_NAME` 的遗留引用，
    而该常量在 P1-a 拆分时已删除 ⇒ 一旦被调用就是 NameError。
    信号现已移到 `<run_id>/signals/`，此处同步改为唯一规则 `signal_path()`。
    """
    return read_json_safe(signal_path(run_id, child_dir_name))


# --------------------------------------------------------------------------- #
# run-id 防呆：路径合法性 + 复用防护（append-only 的硬保护，不靠君子协定）
# --------------------------------------------------------------------------- #
_BAD_RUN_ID_CHARS = ("/", "\\", ":", "*", "?", '"', "<", ">", "|")


def validate_run_id(run_id: str) -> dict:
    """拒绝会让产物写到 `work\\runs\\` 之外或语义不清的 run-id。"""
    problems = []
    if not run_id or not run_id.strip():
        problems.append("为空")
    if any(c in run_id for c in _BAD_RUN_ID_CHARS):
        problems.append(f"含路径/非法字符 {_BAD_RUN_ID_CHARS}")
    if run_id.strip() in (".", "..") or ".." in run_id:
        problems.append("含 '..'")
    if run_id != run_id.strip():
        problems.append("首尾有空白")
    if len(run_id) > 120:
        problems.append("过长(>120)")
    if problems:
        return {"ok": False, "reasons": problems}
    target = (RUNS / run_id).resolve()
    try:
        target.relative_to(RUNS.resolve())
    except ValueError:
        return {"ok": False, "reasons": [f"解析后落在 RUNS 之外：{target}"]}
    return {"ok": True, "target": str(target)}


def run_id_reuse_guard(run_id: str, force: bool) -> dict:
    """run-id 复用防护。

    默认策略（**拒绝**）：若 `work\\runs\\<run-id>\\` 已存在且**非空**，拒绝启动并给出非零退出码。
    理由：既有产物代表已经发生过的运行，覆盖它会违反 append-only 红线；
    「真实生产必须换新 run-id」此前只写在文档里，是君子协定，这里改成硬门禁。
    仅显式传 `--force-reuse-run-id` 才放行（并在产物里留痕）。
    """
    v = validate_run_id(run_id)
    if not v.get("ok"):
        return {"ok": False, "action": "refused_invalid_run_id",
                "reasons": v.get("reasons"), "run_id": run_id}
    rd = RUNS / run_id
    if not rd.exists():
        return {"ok": True, "action": "create_new", "run_dir": str(rd),
                "existing_entries": 0, "forced": False}
    entries = sorted(p.name for p in rd.iterdir())
    if not entries:
        return {"ok": True, "action": "use_existing_empty", "run_dir": str(rd),
                "existing_entries": 0, "forced": False}
    sample = entries[:8]
    if force:
        return {"ok": True, "action": "forced_reuse_nonempty", "run_dir": str(rd),
                "existing_entries": len(entries), "sample": sample,
                "forced": True, "warning": "既有同 run-id 产物可能被覆盖（已显式 --force-reuse-run-id）"}
    return {"ok": False, "action": "refused_nonempty_run_dir", "run_dir": str(rd),
            "existing_entries": len(entries), "sample": sample, "forced": False,
            "hint": "换一个新 --run-id；确需复用请显式加 --force-reuse-run-id"}


# --------------------------------------------------------------------------- #
# 判据哈希与控制面冻结签名（只读既有产物，不自己重算一套）
# --------------------------------------------------------------------------- #
def load_criteria_hashes() -> dict:
    if not CRITERIA_SUMMARY.is_file():
        raise FileNotFoundError(f"判据哈希来源不存在：{CRITERIA_SUMMARY}")
    d = json.loads(CRITERIA_SUMMARY.read_text(encoding="utf-8"))
    out = {"source_path": str(CRITERIA_SUMMARY), "source_sha256": sha256_file(CRITERIA_SUMMARY),
           "source_artifact_version": d.get("artifact_version")}
    for k in ("invariant_criteria_hash", "sweep_spec_hash"):
        if not d.get(k):
            raise ValueError(f"{CRITERIA_SUMMARY.name} 缺少 {k}（禁止自行重算，须先补该产物）")
        out[k] = d[k]
    return out


_FROZEN_CACHE: dict | None = None


def _frozen_all() -> dict:
    global _FROZEN_CACHE
    if _FROZEN_CACHE is None:
        if not FROZEN_PRECHECK.is_file():
            raise FileNotFoundError(f"控制面冻结签名来源不存在：{FROZEN_PRECHECK}")
        _FROZEN_CACHE = json.loads(FROZEN_PRECHECK.read_text(encoding="utf-8"))
        _FROZEN_CACHE["_sha256"] = sha256_file(FROZEN_PRECHECK)
    return _FROZEN_CACHE


def load_frozen_signature(x: float, n1: int) -> dict | None:
    d = _frozen_all()
    for r in d.get("phase2_rows", []):
        try:
            if abs(float(r["x_scale"]) - float(x)) < 1e-12 and int(r["N_w_te1"]) == int(n1):
                return {"area_ptot_geometry": r.get("area_ptot_geometry"),
                        "ptot_boundary_bounding_box": r.get("ptot_boundary_bounding_box"),
                        "intop5_entities": r.get("intop5_entities"),
                        "swr1_entities": r.get("swr1_entities"),
                        "efc1_entities": r.get("efc1_entities"),
                        "source_path": str(FROZEN_PRECHECK),
                        "source_sha256": d.get("_sha256")}
        except (TypeError, ValueError):
            continue
    return None


# --------------------------------------------------------------------------- #
# LT2-C 快速门禁（选择集 / 控制面签名）——复用既有实现，不复制粘贴
# --------------------------------------------------------------------------- #
def _gsp():
    """惰性导入 `scripts/geometry_selection_precheck.py`（它依赖 memsharness，故不在模块顶层导入）。"""
    for p in (str(REPO / "scripts"), str(REPO / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import geometry_selection_precheck as gsp  # noqa: PLC0415
    return gsp


def _is_active(obj) -> bool | None:
    try:
        return bool(obj.isActive())
    except Exception:
        return None


def _ents(fn) -> list[int] | None:
    try:
        return fn()
    except Exception:
        return None


def _rel_diff(a, b) -> float | None:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    denom = max(abs(a), abs(b), 1e-300)
    return abs(a - b) / denom


def _rel_close(a, b, rel=AREA_REL_TOL) -> bool | None:
    d = _rel_diff(a, b)
    return None if d is None else (d <= rel)


def _bbox_close(a, b, rel=BBOX_REL_TOL) -> bool | None:
    if not a or not b or len(a) != len(b):
        return None
    return all(_rel_close(x, y, rel) for x, y in zip(a, b))


def lt2c_quick_gate(java, comp, geom, x: float, n1: int, obj_name: str = "fin") -> dict:
    """LT2-C 快速门禁：每个组合求解**之前**执行。

    检查项（授权 LT2-C 原文）：
      pot1/pot2/gnd1 选择集非空；两两电极实体交集为 0；term1_active=false；
      cir_inactive_verified=true；intop5==swr1==efc1；
      Ptot 控制面 area/bbox 签名与冻结值一致。
    """
    gsp = _gsp()
    entities_of = gsp.entities_of
    checks: dict = {}
    detail: dict = {}

    def sel_of_physics(phys_tag, feat_tag):
        try:
            return entities_of(comp.physics(phys_tag).feature(feat_tag).selection())
        except Exception as exc:
            detail[f"{phys_tag}.{feat_tag}_error"] = f"{type(exc).__name__}: {exc}"
            return None

    pot1 = sel_of_physics("es", "pot1")
    pot2 = sel_of_physics("es", "pot2")
    gnd1 = sel_of_physics("es", "gnd1")
    named_outer = _ents(lambda: entities_of(comp.selection("cyl8")))
    named_inner = _ents(lambda: entities_of(comp.selection("cyl9")))
    intop5 = _ents(lambda: entities_of(comp.cpl("intop5").selection()))
    swr1 = sel_of_physics("acpr", "swr1")
    efc1 = sel_of_physics("acpr", "efc1")

    detail.update(pot1_entities=pot1, pot2_entities=pot2, gnd1_entities=gnd1,
                  named_cyl8_entities=named_outer, named_cyl9_entities=named_inner,
                  intop5_entities=intop5, swr1_entities=swr1, efc1_entities=efc1)

    checks["pot1_nonempty"] = bool(pot1)
    checks["pot2_nonempty"] = bool(pot2)
    checks["gnd1_nonempty"] = bool(gnd1)
    checks["pot1_pot2_overlap_0"] = (len(set(pot1 or []) & set(pot2 or [])) == 0)
    checks["pot1_gnd1_overlap_0"] = (len(set(pot1 or []) & set(gnd1 or [])) == 0)
    checks["pot2_gnd1_overlap_0"] = (len(set(pot2 or []) & set(gnd1 or [])) == 0)
    checks["named_cyl8_eq_pot1"] = (named_outer == pot1) if (named_outer is not None and pot1) else None
    checks["named_cyl9_eq_pot2"] = (named_inner == pot2) if (named_inner is not None and pot2) else None

    term1_active = _is_active(comp.physics("es").feature("term1"))
    checks["term1_active_false"] = (term1_active is False)
    detail["term1_active"] = term1_active

    cir_active = None
    try:
        cir_active = _is_active(comp.physics("cir"))
    except Exception as exc:
        detail["cir_error"] = f"{type(exc).__name__}: {exc}"
    checks["cir_inactive_verified"] = (cir_active is False)
    detail["cir_active"] = cir_active

    eq_swr = (intop5 == swr1) if (intop5 is not None and swr1 is not None) else None
    eq_efc = (intop5 == efc1) if (intop5 is not None and efc1 is not None) else None
    checks["intop5_eq_swr1"] = eq_swr
    checks["intop5_eq_efc1"] = eq_efc
    checks["intop5_eq_swr1_eq_efc1"] = bool(eq_swr and eq_efc)

    frozen = load_frozen_signature(x, n1)
    # 无论冻结签名是否找到，容差证据都要存在（§5）
    tol_ev = {"scope": TOLERANCE_SCOPE, "error": "frozen_signature_not_found",
              "frozen_evidence_run_id": FROZEN_PRECHECK.parent.name,
              "frozen_evidence_path": str(FROZEN_PRECHECK),
              "frozen_evidence_sha256": sha256_file(FROZEN_PRECHECK),
              "area_rel_tol": AREA_REL_TOL, "bbox_rel_tol": BBOX_REL_TOL}
    if frozen is None:
        checks["frozen_signature_found"] = False
        detail["frozen_signature_error"] = f"冻结签名中无 ({x},{n1})；不自行构造参照值"
    else:
        checks["frozen_signature_found"] = True
        checks["frozen_intop5_entities_equal"] = (
            sorted(intop5 or []) == sorted(int(v) for v in (frozen["intop5_entities"] or []))
            if intop5 is not None else None)
        area, call, err = gsp.geometry_area(geom, intop5 or [], obj_name=obj_name)
        bbox, bberr = gsp.geometry_bbox(geom, intop5 or [], obj_name=obj_name)
        detail["area_ptot_geometry"] = area
        detail["area_ptot_geometry_call"] = call
        detail["area_ptot_geometry_error"] = err
        detail["ptot_boundary_bounding_box"] = bbox
        detail["ptot_boundary_bounding_box_error"] = bberr
        detail["area_ptot_geometry_frozen"] = frozen["area_ptot_geometry"]
        detail["ptot_boundary_bounding_box_frozen"] = frozen["ptot_boundary_bounding_box"]
        checks["ptot_surface_area_unchanged"] = _rel_close(area, frozen["area_ptot_geometry"])
        checks["ptot_surface_bbox_unchanged"] = _bbox_close(bbox, frozen["ptot_boundary_bounding_box"])
        detail["frozen_signature_source"] = frozen["source_path"]
        detail["frozen_signature_sha256"] = frozen["source_sha256"]
        # §5 要求 checkpoint 同时保存冻结值 / 当前值 / 相对差 / 两侧 bbox / 容差 / 冻结证据 run_id+sha256
        tol_ev = {
            "scope": TOLERANCE_SCOPE,
            "frozen_area_value": frozen["area_ptot_geometry"],
            "current_area_value": area,
            "area_relative_difference": _rel_diff(area, frozen["area_ptot_geometry"]),
            "frozen_bbox": frozen["ptot_boundary_bounding_box"],
            "current_bbox": bbox,
            "area_rel_tol": AREA_REL_TOL,
            "bbox_rel_tol": BBOX_REL_TOL,
            "frozen_evidence_run_id": Path(frozen["source_path"]).parent.name,
            "frozen_evidence_path": frozen["source_path"],
            "frozen_evidence_sha256": frozen["source_sha256"],
            "frozen_intop5_entities": frozen["intop5_entities"],
            "current_intop5_entities": intop5,
            "area_check_call": call, "area_check_error": err,
            "bbox_check_error": bberr,
            "analytic_geometry_comparison": None,
            "analytic_note": ("本容差**不**用于声称与解析几何一致；"
                              "控制面面积与 2πR² 的 0.271% 差异属另一问题，不得据此放宽本容差"),
        }

    # **fail-closed**：任何一项不是明确的 True（含 None = 取不到证据）都判门禁不通过。
    # 门禁宁可拦住也不放过；因为 None 通常意味着选择集/接口读取失败。
    checks["pass"] = all(v is True for v in checks.values())
    return {"checks": checks, "detail": detail,
            "tolerance_evidence": tol_ev,
            "area_rel_tol": AREA_REL_TOL, "bbox_rel_tol": BBOX_REL_TOL}


# --------------------------------------------------------------------------- #
# 资源时序摘要（读 sidecar 产物）
# --------------------------------------------------------------------------- #
def summarize_timeline(jsonl_f: Path, th: Thresholds) -> dict:
    """从**完整** JSONL 汇总；事件同时给出总数与前 40 条摘要（报告里必须两者并列）。"""
    rows: list[dict] = []
    if jsonl_f.is_file():
        for line in jsonl_f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def vals(key):
        out = []
        for r in rows:
            try:
                if r.get(key) not in (None, ""):
                    out.append(float(r[key]))
            except (TypeError, ValueError):
                pass
        return out

    ws, pk = vals("server_working_set_mb"), vals("server_peak_working_set_mb")
    av, cm = vals("system_available_physical_mb"), vals("commit_available_mb")

    events = []
    for r in rows:
        for kind, cond in (
            ("hard_stop_ws", lambda v: v >= th.ws_hard_stop_mb),
            ("soft_stop_ws", lambda v: th.ws_warning_mb <= v < th.ws_hard_stop_mb),
            ("hard_stop_commit", lambda v: v <= th.commit_hard_stop_mb),
            ("soft_stop_commit", lambda v: th.commit_hard_stop_mb < v <= th.commit_warning_mb),
            ("hard_stop_avail", lambda v: v <= th.physical_avail_hard_stop_mb),
        ):
            key = {"hard_stop_ws": "server_working_set_mb", "soft_stop_ws": "server_working_set_mb",
                   "hard_stop_commit": "commit_available_mb", "soft_stop_commit": "commit_available_mb",
                   "hard_stop_avail": "system_available_physical_mb"}[kind]
            try:
                v = float(r[key])
            except (TypeError, ValueError, KeyError):
                continue
            if cond(v):
                events.append({"t": r.get("timestamp"), "kind": kind, "value": v,
                               "stage": r.get("current_stage")})

    gaps = []
    ts = [r.get("timestamp") for r in rows if r.get("timestamp")]
    for a, b in zip(ts, ts[1:]):
        try:
            d = (time.mktime(time.strptime(b, "%Y-%m-%dT%H:%M:%S"))
                 - time.mktime(time.strptime(a, "%Y-%m-%dT%H:%M:%S")))
        except ValueError:
            continue
        if d > th.gap_limit_s:
            gaps.append({"from": a, "to": b, "gap_s": d})

    solve_rows = [r for r in rows if r.get("current_stage") == "solve"]
    missing = [c for c in ("system_available_physical_mb", "system_memory_load_percent",
                           "commit_available_mb")
               if any(r.get(c) in (None, "") for r in solve_rows)]

    return {
        "timeline_rows": len(rows),
        "timeline_gaps_over_15s": gaps,
        "solve_stage_missing_system_columns": missing,
        "server_ws_mb": {"min": min(ws) if ws else None, "max": max(ws) if ws else None},
        "server_peak_ws_mb": max(pk) if pk else None,
        "system_available_physical_mb": {"min": min(av) if av else None},
        "commit_available_mb": {"min": min(cm) if cm else None, "max": max(cm) if cm else None},
        "commit_warning_samples": sum(1 for v in cm if v <= th.commit_warning_mb),
        "commit_hard_stop_samples": sum(1 for v in cm if v <= th.commit_hard_stop_mb),
        "stop_line_event_count": len(events),
        "stop_line_events_head40": events[:40],
        "stop_line_events_file": str(jsonl_f),
        "stop_line_events_file_sha256": sha256_file(jsonl_f),
        "stop_line_events_truncated_in_report": max(0, len(events) - 40),
        "simulated": any(bool(r.get("simulated")) for r in rows),
    }


def combo_pass_conditions(rows: list[dict], summary: dict, lt2c: dict,
                          cancel_record: dict | None, th: Thresholds) -> dict:
    """单组合验收。**commit 项必须在内**（R0 缺陷 D1 的修正）。

    ---- F5（父 agent 2026-09-15 裁定）：**空集/缺证据不得判通过** ----
    旧写法里四项在"时间线为空"时全为 True：`not []` → True、`... or 0` → `0 < 12288`、
    `.get("commit_hard_stop_samples", 0) == 0` → True ⇒ **"没有任何证据"被当成"没有越线"**。
    同函数里 `min_avail_ge_hard_stop` / `min_commit_gt_hard_stop` 早已显式要求 `is not None`
    ⇒ 标准本来是清楚的，只是这四项漏了。现在一律要求「**显式非空证据 + 阈值判定**」。
    """
    cm = summary.get("commit_available_mb") or {}
    n_rows = summary.get("timeline_rows") or 0
    peak_ws = summary.get("server_peak_ws_mb")
    cm_hard_samples = summary.get("commit_hard_stop_samples")

    def _v_ok(v) -> bool:
        """`|Vdiff| == 2.0`；缺失/非数值一律**不算合格**（不得被 `all()` 静默跳过）。"""
        try:
            return abs(abs(float(v)) - 2.0) < 1e-6
        except (TypeError, ValueError):
            return False

    return {
        "frequency_rows_7": len(rows) == 7,
        # 两个"全称条件"必须先有行，再谈"全部合格"（空集不得冒充通过）
        "failed_frequency_points_0": bool(rows) and all(r.get("solve_status") == "ok" for r in rows),
        "drive_voltage_mismatch_0": bool(rows) and all(_v_ok(r.get("Vdiff_abs")) for r in rows),
        # 监控条件：必须有 ≥1 行样本，才谈得上"没有缺口 / 没有缺列"
        "monitoring_ok": (n_rows >= 1 and not summary["timeline_gaps_over_15s"]
                          and not summary["solve_stage_missing_system_columns"]),
        # ⚠️ 键名**不得内嵌数字**：取值来自 `th`（生效阈值），演练覆盖时数字会变
        # （F1：旧名 peak_ws_lt_12288 / min_avail_ge_4096 / min_commit_gt_4096 与实际取值可能不符）。
        # 用的是哪套阈值由 checkpoint 的 `thresholds` + `thresholds_provenance` **单源**给出。
        # peak 必须**有值**，否则无法证明没越线（F5）
        "peak_ws_lt_hard_stop": (peak_ws is not None and peak_ws < th.ws_hard_stop_mb),
        "min_avail_ge_hard_stop": (summary.get("system_available_physical_mb") or {}).get("min") is not None
        and summary["system_available_physical_mb"]["min"] >= th.physical_avail_hard_stop_mb,
        # --- 缺陷 D1：commit 必须作为验收条件出现，不得再漏 ---
        # F5：计数必须**有值**（缺列不得由默认 0 冒充"零次越线"）**且必须有 ≥1 行样本**
        # ——实测：`summarize_timeline` 对空时间线返回的是整数 0（不是 None），
        # 所以"仅判非 None"不够，必须显式要求非空证据。
        "commit_hard_stop_samples_0": (n_rows >= 1 and cm_hard_samples is not None
                                       and cm_hard_samples == 0),
        "min_commit_gt_hard_stop": (cm.get("min") is not None
                                    and cm["min"] > th.commit_hard_stop_mb),
        "lt2c_quick_gate_pass": bool((lt2c or {}).get("checks", {}).get("pass")),
        "no_cancel_triggered": cancel_record is None,
    }


def all_conditions_true(conditions: dict) -> tuple[bool, list[str]]:
    """**唯一的**条件聚合口径（单一真源；两处写状态都只走这里）。

    判通过的条件：**非空** 且 **每一项 `is True`**（身份比较，不是真值判断）。
      · 用 `v is True` 而非 `all(d.values())`：`1` / `0` / `None` / 字符串都**不算通过**，
        避免"看起来像布尔"的值靠真值冒充结论（fail-closed）；
      · 非布尔值一律登记为**形状违规**并回报键名：`pass_conditions` **只许放布尔条件**，
        计数器/度量放 checkpoint **顶层**。

    背景（实测缺陷，r3f 暴露）：F2 修复曾把 `hard_stop_verdict_sample_count`（整数）塞进
    `pass_conditions`，而旧聚合是 `all(pc.values())` ⇒ 生产路径上该计数器的**正确值 0**
    被当成假 ⇒ 全部实质条件为真、状态却是 `fail_or_limited`，批次被误判为 BLOCKED。
    这与"空集判通过"是同一类错误：用**值与真假的混同**代替显式判定。
    """
    violations = [k for k, v in conditions.items() if not isinstance(v, bool)]
    ok = bool(conditions) and not violations and all(v is True for v in conditions.values())
    return ok, violations


# --------------------------------------------------------------------------- #
# 硬停动作：verified_emergency_termination（§7.1）
#
# **命名纪律**：本架构无法证明能在另一个线程安全地调用同一 MPh client 去取消阻塞中的
# `study.run()`。因此任何路径都**不得**称为"已验证的 graceful cancel"。
# 唯一具备可验证语义的动作是：核对归属后结束本任务 server，即
# `verified_emergency_termination` —— 归属（port owner PID + 进程启动时间 + run_id 标识）
# 三者核对通过才终止，终止后必须二次确认。
#
# 全部外部副作用经 `deps` 注入，因此可在**不启动 COMSOL**的前提下做故障注入测试。
# --------------------------------------------------------------------------- #
def _stop_process(pid: int) -> dict:
    """终止单个 PID 并回传命令退出码（不是"调用了就算成功"）。"""
    out = run_ps(f"try {{ Stop-Process -Id {int(pid)} -Force -ErrorAction Stop; 'RC|0' }} "
                 f"catch {{ 'RC|1|' + $_.Exception.Message }}")
    parts = out.split("|", 2)
    rc = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
    return {"cmd": f"Stop-Process -Id {int(pid)} -Force", "rc": rc,
            "output": out[:300]}


class TerminationDeps:
    """终止路径的外部依赖集合（真实运行用默认值；测试注入假实现）。"""

    def __init__(self, *, port_open=None, port_owner_pid=None, proc_identity=None,
                 proc_exists=None, terminate=None, verify=None, sleep=None):
        self.port_open = port_open or globals()["port_open"]
        self.port_owner_pid = port_owner_pid or globals()["port_owner_pid"]
        self.proc_identity = proc_identity or globals()["proc_identity"]
        self.proc_exists = proc_exists or globals()["proc_exists"]
        self.terminate = terminate or _stop_process
        self.verify = verify or verify_termination
        self.sleep = sleep or time.sleep


# --------------------------------------------------------------------------- #
# 触发分类（D-C）：**只有真的越线样本才能叫 hard stop**
# --------------------------------------------------------------------------- #
THRESHOLD_CROSS_PATTERNS = ("ws_hard_stop(", "physical_avail_hard_stop(", "commit_hard_stop(")


# --------------------------------------------------------------------------- #
# 终止来源归属 + 正常收尾（父 agent 2026-09-14 裁定：r3/r3b 实测现象必须在硬停演练前修）
# --------------------------------------------------------------------------- #
# 实测现象（r3 与 r3b **逐字段相同**）：worker 写完 checkpoint 并置 stage=closed/stop=true
# 之后、进程退出之前，sampler 已由 worker 自己正常停掉 ⇒ supervisor 轮询看到
# `sidecar_exited` 并误走 enforce 分支，于是：
#   ① 一次**正常收尾**的 run 里留下 `hard_stop_enforce` 触发记录 + signals 文件；
#   ② `enforced=True` 跳过 `proc.wait(30)` ⇒ `worker_returncode` 丢成 null。
# 本轮后果无害（steps 里没有 terminate_server，二次确认 verified），但**硬停演练的核心证据
# 就是触发记录**——若正常收尾也产出同类记录，演练证据当场失去判读力。故：
#   - 轮询加「正常完成守卫」：有正常完成的**正面证据**时不 enforce，等自然退出、记真实退出码；
#   - 触发记录区分 `trigger_kind`（正常收尾 vs 真越线）与 `enforced_by`（谁要求终止）。
TRIGGER_KIND_NORMAL_COMPLETION = "normal_completion_sidecar_exit"
ENFORCED_BY_VALUES = ("drill_gate", "resource_gate", "integrity_gate", "worker_startup_gate",
                      "worker_requested_gate", "sampler_verdict_gate", "sidecar_health_gate",
                      "normal_completion_timeout_gate", "unclassified_gate")
ENFORCED_BY_DEFINITION = (
    "enforced_by = 「谁要求终止」的**单一**归属标签，用于一键区分演练与真实资源事件："
    "drill_gate = 演练阈值越线（--drill，**不是**真实资源越线）；"
    "resource_gate = 真实资源阈值越线（trigger_kind=threshold_crossed）；"
    "integrity_gate = 完整性失败；worker_startup_gate = worker 启动超时；"
    "worker_requested_gate = worker 自己 cancel_requested；"
    "sampler_verdict_gate = sidecar verdict=hard_stop；"
    "sidecar_health_gate = sidecar 退出/停更（不依赖 verdict）；"
    "normal_completion_timeout_gate = 正常收尾已判定但 worker 超过 "
    "NORMAL_COMPLETION_GRACE_S 仍未退出（有界升级，见守卫注释）；"
    "unclassified_gate = 其余（fail-closed 记录，不得当资源事件）。"
    "正常收尾**不产生** enforce ⇒ enforced_by=null 且 trigger_kind="
    + TRIGGER_KIND_NORMAL_COMPLETION + "。")


def classify_enforced_by(action_source: str | None, trigger_kind: str | None,
                         drill: bool = False) -> str:
    """把「谁要求终止」压成**单一**标签（演练 / 资源 / 完整性 …一眼可辨）。

    `drill` 优先：演练用压低阈值，`trigger_kind` 同样是 `threshold_crossed`，
    若不让演练标志先判，演练记录会被读成真实资源硬停。
    """
    if drill:
        return "drill_gate"
    if trigger_kind == "threshold_crossed":
        return "resource_gate"
    if trigger_kind == "integrity_failure":
        return "integrity_gate"
    if trigger_kind == "worker_startup_failure":
        return "worker_startup_gate"
    if action_source == "worker_state.cancel_requested":
        return "worker_requested_gate"
    if action_source == "sampler_state.verdict":
        return "sampler_verdict_gate"
    if action_source == "sidecar_health":
        return "sidecar_health_gate"
    if action_source == "normal_completion_timeout":
        return "normal_completion_timeout_gate"
    return "unclassified_gate"


def classify_trigger(ss: dict, ws: dict, action: dict,
                     th: Thresholds | None = None, clock=None,
                     redact: bool = False) -> dict:
    """把"为什么要终止"分类，避免把基础设施故障伪装成资源硬停（D-B/D-C）。

    返回 `trigger_kind` 与 `is_hard_stop`；`threshold_evidence` 只在真的越线时给出。
    `th` 必须是**生效阈值**（演练时含覆盖值），否则证据里会记成默认值（实测踩到）。
    `clock`/`redact` 供确定性模式使用：固定时间戳、隐去真实 PID，使本记录可逐字节复算。
    """
    th = th or Thresholds()
    clk = clock or now_iso
    reasons = list(ss.get("reasons") or [])
    crossed = [r for r in reasons if any(p in r for p in THRESHOLD_CROSS_PATTERNS)]
    idx = ss.get("sample_index")
    base = {"at": clk(), "decided": action,
            "pid_redacted_for_determinism": bool(redact),
            "sampler_state": {"verdict": ss.get("verdict"), "reasons": reasons,
                              "warnings": ss.get("warnings"),
                              "sample_index": idx,
                              "last_sample_ts": ss.get("last_sample_ts")},
            "worker_state": {"pid": None if redact else ws.get("pid"),
                             "sampler_pid": None if redact else ws.get("sampler_pid"),
                             "worker_pid": None if redact else ws.get("worker_pid"),
                             "cancel_requested": ws.get("cancel_requested"),
                             "cancel_reason": ws.get("cancel_reason"),
                             "stage": ws.get("stage"),
                             "worker_state_present": bool(ws)}}

    # 真的越线：verdict=hard_stop 且 reasons 里含阈值穿越词，且已有 ≥2 个采样
    if ss.get("verdict") == "hard_stop" and crossed and isinstance(idx, int) and idx >= 2:
        return {**base, "trigger_kind": "threshold_crossed", "is_hard_stop": True,
                "threshold_evidence": {
                    "sample_index": idx, "reasons": crossed, "all_reasons": reasons,
                    "counters": ss.get("counters"), "last_sample_ts": ss.get("last_sample_ts"),
                    "thresholds": th.to_dict(),
                    "consecutive_required": th.consecutive_samples,
                    "note": "连续样本越线由 rt_gate.GateEngine 判定（不得由 sidecar 失效推导）"}}

    # 正常收尾（裁定：「正常完成守卫」）：**不是**终止要求，也**不是**资源事件。
    # 顺序关键：真实的越过阈值分支在其之前 ⇒ 真资源事件**永远不会**被降级成「正常收尾」。
    if action.get("source") == "normal_completion_guard":
        return {**base, "trigger_kind": TRIGGER_KIND_NORMAL_COMPLETION, "is_hard_stop": False,
                "enforced": False, "enforced_by": None,
                # 明示"本次未发生终止"（父 agent 裁定 B）：读者不必靠解读文件名或 trigger_kind
                "termination_performed": False, "enforcement_requested": False,
                "normal_completion_markers": list(action.get("reason") or []),
                "reason": ("worker 已产出 checkpoint / 已宣告 stage=closed ⇒ 这是**正常收尾**："
                           "sidecar 退出是 worker 自己停的，不得据此 enforce"),
                "wording_note": ("本记录**不是**终止要求、**不是**资源事件：trigger_kind="
                                 + TRIGGER_KIND_NORMAL_COMPLETION
                                 + "；只有 threshold_crossed 才是资源硬停")}

    # 以下都不是资源硬停 —— 显式区分，便于分类与追责
    if not ws:
        return {**base, "trigger_kind": "worker_startup_failure", "is_hard_stop": False,
                "reason": "supervisor 未读到 worker_state（worker 未起来或未登记）"}
    if not ws.get("sampler_pid"):
        return {**base, "trigger_kind": "worker_startup_failure", "is_hard_stop": False,
                "reason": "worker 未登记 sampler_pid"}
    if idx in (None, 0):
        return {**base, "trigger_kind": "integrity_failure", "is_hard_stop": False,
                "reason": "sampler 在首个样本之前不可用/退出（非资源硬停）"}
    if ss.get("verdict") == "hard_stop" and not crossed:
        return {**base, "trigger_kind": "sample_gap_or_health", "is_hard_stop": False,
                "reason": f"硬线来自采样空档/健康判定而非阈值：{reasons}"}
    return {**base, "trigger_kind": "unclassified_failure", "is_hard_stop": False,
            "reason": f"无法判定为资源硬停：verdict={ss.get('verdict')}, reasons={reasons}"}


def verified_emergency_termination(*, child_dir: Path, expected_pid: int | None,
                                   identity_at_launch: dict | None, run_id: str,
                                   trigger: dict, worker_pid: int | None = None,
                                   deps: TerminationDeps | None = None,
                                   grace_s: float = HARD_STOP_GRACE_S,
                                   reclaim_worker_s: float = WORKER_RECLAIM_AFTER_S,
                                   clock=None, redact: bool = False) -> dict:
    """§7.1 的硬停动作序列（全部留痕，返回结构化记录）。

    `clock` 可注入（默认墙钟）⇒ 确定性模式下产出的证据可逐字节复算（G1）。
    """
    deps = deps or TerminationDeps()
    clk = clock or now_iso
    rec: dict = {"action": "verified_emergency_termination", "at": clk(),
                 "run_id": run_id, "trigger": trigger, "expected_pid": expected_pid,
                 "identity_at_launch": identity_at_launch, "worker_pid": worker_pid,
                 # 裁定 3：谁要求终止（drill_gate / resource_gate / … 一眼可辨）
                 "enforced_by": trigger.get("enforced_by"),
                 "enforced_by_definition": ENFORCED_BY_DEFINITION,
                 "steps": [], "refused": None, "termination": None,
                 "post_verification": None, "worker_reclaimed": None,
                 "naming_note": ("本动作按 §7.1 命名为 verified_emergency_termination；"
                                 "**不是**已验证的 COMSOL graceful cancel")}

    # 1) 冻结新投递（由 run_supervisor 落实，这里留痕）
    rec["steps"].append({"step": "freeze_new_delivery", "ok": True})

    # 2) 保存触发记录（**必带 trigger_kind**；只有 threshold_crossed 才算资源硬停）
    kind = trigger.get("trigger_kind") or "unclassified_failure"
    is_hs = bool(trigger.get("is_hard_stop"))
    trig = {"saved_at": clk(), "run_id": run_id,
            "trigger_kind": kind, "is_hard_stop": is_hs,
            # 裁定：把「谁要求终止」也提到**本记录顶层**，使演练的终止记录一眼可辨
            # （不必下钻到 trigger 子对象）：drill_gate / resource_gate / … / null（正常收尾）
            "enforced_by": trigger.get("enforced_by"),
            "is_drill_run": trigger.get("is_drill_run"),
            "pid_redacted_for_determinism": bool(redact),
            "wording_note": ("仅当 trigger_kind == 'threshold_crossed' 时本记录才是"
                             "资源硬停；其余均为基础设施/完整性故障，不得称 hard stop"),
            "trigger": trigger,
            "expected_pid": None if redact else expected_pid,
            "identity_at_launch": None if redact else identity_at_launch,
            "worker_pid": None if redact else worker_pid}
    w = atomic_write_json(child_dir / TRIGGER_FILE_NAME, trig)
    rec["trigger_kind"] = kind
    rec["is_hard_stop"] = is_hs
    rec["steps"].append({"step": "save_trigger_record", "ok": bool(w.get("ok")),
                         "path": w.get("path"), "error": w.get("error")})

    # 3) 请求 worker 正常结束 —— 写 **<run_id>/signals/**（不在 child 目录内，见 D-A）
    sp = signal_path(run_id, child_dir.name)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sig = {"writer": "lt2_supervisor", "request": "graceful_worker_end",
           "child_dir_name": child_dir.name,
           "trigger_kind": kind, "is_hard_stop": is_hs,
           "reason": trigger.get("reasons") or trigger.get("reason"),
           "requested_at": clk()}
    w2 = atomic_write_json(sp, sig)
    rec["signal_path"] = str(sp)
    rec["steps"].append({"step": "request_worker_end", "ok": bool(w2.get("ok")),
                         "path": w2.get("path"), "note": "写 <run_id>/signals/，不写 child 目录"})

    # 4) 宽限期：worker 与端口若能自行退出则无需终止
    waited = 0.0
    while waited < grace_s:
        worker_alive = bool(worker_pid and deps.proc_exists(worker_pid))
        if (not deps.port_open(PORT)) and not worker_alive:
            break
        deps.sleep(1.0)
        waited += 1.0
    worker_alive = bool(worker_pid and deps.proc_exists(worker_pid))
    rec["grace"] = {"grace_s": grace_s, "waited_s": waited, "worker_alive": worker_alive,
                    "port_open": deps.port_open(PORT)}
    if (not deps.port_open(PORT)) and not worker_alive:
        rec["steps"].append({"step": "grace_period_self_exit", "ok": True})
        rec["termination"] = {"performed": False, "reason": "self_exited_within_grace"}
        rec["post_verification"] = deps.verify(expected_pid, None, PORT)
        return rec

    # 5) 归属核验：port owner PID + 进程启动时间 + run_id
    actual = deps.port_owner_pid(PORT)
    own = port_owner_ok(expected_pid, actual, deps.port_open(PORT))
    cur = deps.proc_identity(expected_pid)
    ident_match = bool(identity_at_launch and cur
                       and identity_at_launch.get("start_filetime") == cur.get("start_filetime")
                       and identity_at_launch.get("pid") == cur.get("pid"))
    checks = {"port_owner": own, "port_owner_actual_pid": actual,
              "identity_at_launch": identity_at_launch, "identity_now": cur,
              "identity_match": ident_match, "run_id": run_id}
    rec["ownership_checks"] = checks

    if not (own.get("ok") and ident_match):
        rec["refused"] = {"reason": "REFUSED_identity_or_ownership_check_failed",
                          "note": "归属/身份核验不通过 ⇒ **拒绝终止**，只记录并上报",
                          "checks": checks}
        rec["steps"].append({"step": "verify_ownership", "ok": False})
        rec["termination"] = {"performed": False, "reason": rec["refused"]["reason"]}
        return rec
    rec["steps"].append({"step": "verify_ownership", "ok": True})

    # 6) 终止本任务 server
    t = deps.terminate(int(expected_pid))
    rec["termination"] = {"performed": True, "pid": expected_pid, "command": t}
    rec["steps"].append({"step": "terminate_server", "ok": True, "command": t})

    # 7) 终止后**二次确认**（PID 消失 / 端口关闭 / 无意外 server / 命令退出码）
    t_rc = t.get("rc") if isinstance(t, dict) else None
    pv = deps.verify(expected_pid, t_rc, PORT)
    rec["post_verification"] = pv
    rec["steps"].append({"step": "post_termination_verification",
                         "ok": bool(pv.get("verified")), "checks": pv})

    # 8) 回收本任务 worker
    if worker_pid:
        waited2 = 0.0
        while waited2 < reclaim_worker_s and deps.proc_exists(worker_pid):
            deps.sleep(1.0)
            waited2 += 1.0
        if deps.proc_exists(worker_pid):
            wt = deps.terminate(int(worker_pid))
            gone = _wait_until(lambda: not deps.proc_exists(worker_pid), timeout_s=10.0,
                               step_s=0.5)
            rec["worker_reclaimed"] = {"pid": worker_pid, "terminated": True,
                                       "waited_s": waited2, "command": wt,
                                       "pid_absent_after": gone["ok"],
                                       "pid_absent_wait": gone}
        else:
            rec["worker_reclaimed"] = {"pid": worker_pid, "terminated": False,
                                       "waited_s": waited2,
                                       "note": "worker 在宽限期内自行退出"}
    return rec


# --------------------------------------------------------------------------- #
# 决策函数（supervisor 与 dry-run **共用同一份逻辑**）
# --------------------------------------------------------------------------- #
def decide_next_action(gate_verdict: dict, health: dict,
                       worker_state: dict | None = None) -> dict:
    """§7.1：supervisor 每轮**同时**检查 sidecar health + state.verdict + reasons + cancel_requested。

    顺序很重要：**先看 gate verdict**，再看 worker 的 cancel_requested，最后才看 sidecar 健康。
    这样"sidecar 正常运行 + verdict=hard_stop"也会立刻动作，而不是等到 sidecar 停更才反应
    （v1 的缺陷：只查 sidecar_health，于是硬线触发时 supervisor 仍认为一切健康）。
    """
    ws = worker_state or {}
    if gate_verdict.get("verdict") == "hard_stop":
        return {"action": "hard_stop_enforce", "source": "sampler_state.verdict",
                "reason": gate_verdict.get("reasons"),
                "warnings": gate_verdict.get("warnings")}
    if ws.get("cancel_requested"):
        return {"action": "hard_stop_enforce", "source": "worker_state.cancel_requested",
                "reason": ws.get("cancel_reason")}
    if health.get("verdict") == "hard_stop":
        return {"action": "hard_stop_enforce", "source": "sidecar_health",
                "reason": health.get("reasons"),
                "note": "sidecar 退出或时间线停更（不依赖 verdict）"}
    return {"action": "continue", "reason": [], "source": "ok"}


def decide_after_combo(engine: GateEngine, combo_pass: bool) -> dict:
    """组合结束后：软线只阻止**下一组合**。"""
    if not combo_pass:
        return {"deliver_next": False, "reason": "combo_failed"}
    if engine.blocks_next_combination():
        return {"deliver_next": False, "reason": "soft_line_blocks_next_combination",
                "warnings_seen": engine.warnings_seen, "hard_stops": engine.hard_stops}
    return {"deliver_next": True, "reason": None}


# --------------------------------------------------------------------------- #
# 组合 worker（每个组合一个全新进程 → 一个全新 client / server）
# --------------------------------------------------------------------------- #
def sampler_cmd_for(args, child_dir: Path, run_id: str,
                    simulate: int | None = None,
                    simulate_profile: str | None = None) -> list[str]:
    """构造 sidecar 命令（唯一处）：把 drill 阈值与确定性时钟一并传给 sidecar。

    `simulate>0` 只给**假 worker**用（无 COMSOL 的接线冒烟测试）；
    真 worker 必须留空 —— 否则 sidecar 会跑模拟样本而不是读真实资源。
    """
    cmd = [sys.executable, str(SIDECAR), "--run-id", run_id,
           "--state-dir", str(child_dir), "--interval", str(args.interval)]
    if simulate is not None:
        cmd += ["--simulate", str(int(simulate))]
        if simulate_profile:
            cmd += ["--simulate-profile", simulate_profile]
    if getattr(args, "drill", False):
        cmd += ["--drill"]
        for k, flag in (("ws_hard_stop_mb", "--ws-hard-stop-mb"),
                        ("commit_hard_stop_mb", "--commit-hard-stop-mb"),
                        ("physical_hard_stop_mb", "--physical-hard-stop-mb")):
            v = getattr(args, k, None)
            if v is not None:
                cmd += [flag, str(v)]
    if getattr(args, "fixed_timestamps", False):
        cmd += ["--fixed-timestamps"]
    return cmd


# --------------------------------------------------------------------------- #
# 求解后收尾路径（D-D：抽成可测函数）
#
# 真机 run `lt2-resource-confirm-x080-n02-postpagefile-r2` 求解成功（749.5 s，154 采样全 ok），
# 却在 solve 返回的那一秒抛 `NameError: name 'state_f' is not defined` —— 该名字是 P1-a
# 单写者拆分前的遗留引用。因为整段收尾逻辑长在 worker 里、冒烟测试够不到，所以没被覆盖。
# 现把「抽 rows → 写 raw_rows/rows → 资源摘要 → 验收条件 → 原子写 checkpoint」抽成本函数，
# 由真 worker 与测试**共用同一份实现**。
# --------------------------------------------------------------------------- #
def extract_rows(freqs, cx, freq_of, x, n1, nel, solve_s) -> list[dict]:
    """抽取每个频点的结果行（不依赖 numpy/MPh，便于用假求值器测试）。"""
    rows: list[dict] = []
    for i in range(len(freqs)):
        try:
            fhz = freq_of(i)
        except Exception:
            fhz = None
        vo, vi, vr = cx("ave_outer(V)", i), cx("ave_inner(V)", i), cx("ave_ref(V)", i)
        p = cx("Ptot", i)[0]
        rows.append({
            "x_scale": x, "N_w_te1": int(n1),
            "freq_MHz": (fhz / 1e6) if fhz else None,
            "Ptot_W": p, "Vave_mps": cx("Vave", i)[0],
            "Ptot_norm": None, "Vave_norm": None,
            "V_center_re": cx("V_center", i)[0], "V_center_im": cx("V_center", i)[1],
            "V_outer_re": vo[0], "V_inner_re": vi[0],
            "V_ref_abs": None if vr[0] is None else abs(complex(*vr)),
            "Vdiff_abs": (abs(complex(*vo) - complex(*vi))
                          if vo[0] is not None and vi[0] is not None else None),
            "I_inner_abs": "", "I_outer_abs": "",
            "electrical_current_metrics_excluded": "true",
            "electrical_current_exclusion_reason": "LT0_C_KCL_relative_gt_1pct",
            "mesh_element_count": nel, "solve_seconds": solve_s,
            "drive_mode": DRIVE_MODE,
            "geometry_status": "ok", "mesh_status": "ok",
            "solve_status": "ok" if p is not None else "failed"})
    for r in rows:
        if r.get("Vdiff_abs") and r["Ptot_W"] is not None:
            r["Ptot_norm"] = r["Ptot_W"] / (float(r["Vdiff_abs"]) ** 2)
            r["Vave_norm"] = r["Vave_mps"] / float(r["Vdiff_abs"])
    return rows


def finalize_after_solve(*, run_id: str, idx: int, attempt: int, child_dir: Path,
                         x, n1, freqs, rows: list[dict], lt2c: dict, th: Thresholds,
                         cancel_rec, set_state, meta: dict,
                         jsonl_f: Path | None = None, clock=None) -> dict:
    """求解返回后的收尾（**唯一实现**，真 worker 与测试共用）。

    写入：`raw_rows.csv` → `rows.csv` → `checkpoint.json`（原子）。
    返回 checkpoint 内容。任何写失败都抛异常（不静默）。
    `clock` 可注入 ⇒ 确定性模式下 `written_at` 也可复算（否则 checkpoint 哈希每次不同）。
    """
    clk = clock or now_iso
    jsonl_f = jsonl_f or (child_dir / "resource_timeline.jsonl")
    raw_f = child_dir / "raw_rows.csv"
    if rows:
        with raw_f.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    artifact_sha = sha256_file(raw_f) if raw_f.is_file() else None
    rows = [dict(r) for r in rows]
    for r in rows:
        r["source_run_id"] = run_id
        r["source_artifact_sha256"] = artifact_sha
    rows_f = child_dir / "rows.csv"
    if rows:
        with rows_f.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    summary = summarize_timeline(jsonl_f, th)
    # 时间线**只读一次**（同一份快照供两类计数使用；**没有**第二条按 cancel_rec 门控的读取路径）：
    #   · F2：hard-stop verdict 行数（`no_hard_stop_verdict_samples` + count）
    #   · F3：warning verdict 行数（`blocks_next_combination` + count）
    # 两者的"读失败"处置**同规**：None ⇒ 判 False / 判阻塞（fail-closed，不得由空集冒充通过）。
    timeline_parsed: list[dict] | None
    try:
        timeline_parsed = [json.loads(l) for l in
                           jsonl_f.read_text(encoding="utf-8", errors="replace").splitlines()
                           if l.strip()]
    except Exception:
        timeline_parsed = None
    # F2 修复：读失败 ⇒ None ⇒ 判 False（**fail-closed**，修掉旧代码"空集判通过"的隐患）
    hard_stop_verdict_samples: int | None = (
        None if timeline_parsed is None
        else sum(1 for v in timeline_parsed if v.get("verdict") == "hard_stop"))
    # F3 修复：warning 计数**同样始终统计**（旧代码只在 cancel_rec is None 时取值 ⇒ 取消场景恒 False，
    # 即"取消的 child 一律声称没有软线告警"）；读失败 ⇒ None ⇒ 阻塞下一组合（fail-closed）
    warning_verdict_samples: int | None = (
        None if timeline_parsed is None
        else sum(1 for v in timeline_parsed if v.get("verdict") == "warning"))
    pc = combo_pass_conditions(rows, summary, lt2c, cancel_rec, th)
    # F5（父 agent 2026-09-15）：**空时间线**同样不得冒充通过 —— 旧写法 `count == 0` 在
    # "一行样本都没有"时为 True（计数 0），但那是"没有证据"而非"没有越线"。
    # 现在要求解析成功**且**至少 1 行样本，才允许宣称"没有 hard-stop 样本"。
    parsed_rows: int | None = None if timeline_parsed is None else len(timeline_parsed)
    pc["no_hard_stop_verdict_samples"] = (bool(parsed_rows)
                                          and hard_stop_verdict_samples == 0)
    # F2 计数**不进** `pass_conditions`（只放布尔条件）：计数器 0 是"通过值"，一旦混进
    # 条件字典，任何真值聚合都会把它读成假（r3f 实测缺陷）。计数与 F3 的
    # `warning_verdict_sample_count` 对称，放 checkpoint 顶层。
    conditions_ok, condition_shape_violations = all_conditions_true(pc)

    ck = {"run_id": run_id, "child_index": idx, "attempt": attempt,
          "child_dir": str(child_dir), "combo": [x, int(n1)],
          "drive_mode": DRIVE_MODE, "freqs_MHz": list(freqs),
          "model_sha256": sha256_file(MODEL),
          "script_sha256": sha256_file(SELF),
          "sampler_sha256": sha256_file(SIDECAR),
          "criteria_hashes": load_criteria_hashes(),
          "frozen_signature_source": str(FROZEN_PRECHECK),
          "frozen_signature_sha256": sha256_file(FROZEN_PRECHECK),
          "tolerance_evidence": (lt2c or {}).get("tolerance_evidence"),
          "thresholds": th.to_dict(),
          "server_lifecycle_size": SERVER_LIFECYCLE_SIZE,
          "attended_operation": ATTENDED_OPERATION,
          "rows": rows, "rows_artifact_sha256": artifact_sha,
          "rows_csv_sha256": sha256_file(rows_f) if rows_f.is_file() else None,
          "resource_summary": summary,
          "lt2c_quick_gate": lt2c,
          "cancel_record": cancel_rec,
          # F3：与 hard-stop 计数**同源**（同一份时间线快照，无 cancel_rec 门控的第二条路径）；
          # 读失败 ⇒ None ⇒ 判**阻塞下一组合**（无法证明"没有软线告警"就不投递下一组合）。
          # F5（父 agent 2026-09-15，同类按同一原则）：**空时间线**同样无法证明
          # "没有软线告警" ⇒ 判阻塞（空集不得冒充"无告警"）。
          "blocks_next_combination": (True if (parsed_rows is None or parsed_rows < 1
                                               or warning_verdict_samples is None)
                                      else warning_verdict_samples > 0),
          "warning_verdict_sample_count": warning_verdict_samples,
          # F2 计数（与 F3 对称，顶层单源；**不在** pass_conditions 里）
          "hard_stop_verdict_sample_count": hard_stop_verdict_samples,
          # 形状违规**始终**落盘（正常为空列表）：非布尔值混进条件字典时可被事后审计发现
          "pass_condition_shape_violations": condition_shape_violations,
          "status": "pass" if conditions_ok else "fail_or_limited",
          "pass_conditions": pc,
          "written_at": clk(), "simulated": False}
    ck.update(meta)

    # 这一行就是 D-D 崩溃点：原来写的是 set_state(state_f, stage="checkpoint")
    set_state(stage="checkpoint")
    r = atomic_write_json(child_dir / "checkpoint.json", ck)
    if not r.get("ok"):
        raise RuntimeError(f"checkpoint 原子写失败: {r.get('error')}")
    return ck


def run_fake_combo_worker(args) -> int:
    """**接线冒烟测试用的假 worker**（绝不启动 COMSOL、不 import mph）。

    走与真 worker 相同的文件协议：建/校验 child 目录 → 写 worker_state →
    拉起真实 sidecar（模拟样本）→ 写 checkpoint → 置 stop。
    用途：验证「supervisor 拉起 worker → worker 接受自己的 child 目录 → sampler 产出时间线」
    这条链路，正是 D-A 回归漏测的那条。
    """
    rd = RUNS / args.run_id
    x, n1 = args.combo
    idx = args.child_index
    attempt = getattr(args, "attempt", 1)
    child_dir = rd / CHILD_DIR_FMT.format(idx=idx, attempt=attempt)
    fixed = bool(getattr(args, "fixed_timestamps", False))
    clk = (lambda: FIXED_CLOCK_ISO) if fixed else now_iso
    worker_f = child_dir / WORKER_STATE_NAME

    # 与真 worker **完全相同**的 append-only 守卫（冒烟测试要验证它不误伤正常路径）
    if child_dir.exists() and any(child_dir.iterdir()):
        atomic_write_json(rd / f"{child_dir.name}{REFUSED_FILE_SUFFIX}",
                          {"at": clk(), "reason": "child_dir_exists_nonempty",
                           "child_dir": str(child_dir), "role": "fake-combo-worker",
                           "note": "拒绝复用非空 child 目录（append-only）"})
        return 1
    child_dir.mkdir(parents=True, exist_ok=True)

    def set_state(**kw):
        cur = read_worker_state(child_dir)
        cur.update(kw)
        cur["writer"] = "lt2_fake_combo_worker"
        cur.setdefault("updated_at", clk())
        write_own_state(worker_f, cur)

    set_state(pid=None, combo=f"({x},{n1})", stage="startup", stop=False,
              cancel_requested=False, worker_pid=os.getpid(), child_index=idx,
              attempt=attempt, child_dir=str(child_dir), simulated=True,
              drill=bool(getattr(args, "drill", False)))

    drill_on = bool(getattr(args, "drill", False))
    sampler = subprocess.Popen(
        sampler_cmd_for(args, child_dir, args.run_id, simulate=6,
                        simulate_profile=("ramp_ws" if drill_on else "safe")),
        stdout=DEVNULL, stderr=DEVNULL)
    set_state(sampler_pid=sampler.pid, stage="solve")
    try:
        sampler.wait(timeout=120)
    except Exception:
        sampler.kill()
    sampler_rc = sampler.returncode

    # 演练/硬停场景：若 sidecar 已判 hard_stop，模拟"study 仍阻塞"，
    # 让 supervisor 有机会在阻塞期间因 verdict 动作（这正是 U1 要验的场景）。
    ss_now = read_sampler_state(child_dir)
    if ss_now.get("verdict") == "hard_stop":
        set_state(stage="solve_blocked_simulated")
        time.sleep(float(getattr(args, "blocked_hold_s", 4.0)))

    n_samples = 5
    rows = [{"x_scale": x, "N_w_te1": int(n1), "freq_MHz": 5.0, "Ptot_W": 1.0e-6,
             "Vave_mps": 1.0e-2, "Vdiff_abs": 2.0, "solve_status": "simulated",
             "drive_mode": DRIVE_MODE, "source_run_id": args.run_id,
             "source_artifact_sha256": None}]
    raw_f = child_dir / "raw_rows.csv"
    with raw_f.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    art = sha256_file(raw_f)
    for r in rows:
        r["source_artifact_sha256"] = art
    rows_f = child_dir / "rows.csv"
    with rows_f.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    th, drill_rec = resolve_thresholds(args)
    summary = summarize_timeline(child_dir / "resource_timeline.jsonl", th)
    ck = {"run_id": args.run_id, "child_index": idx, "attempt": attempt,
          "child_dir": str(child_dir), "combo": [x, int(n1)],
          "drive_mode": DRIVE_MODE, "freqs_MHz": list(args.freqs),
          "freqs_parse": getattr(args, "freqs_parse", None),
          "freeze_id": getattr(args, "freeze_id", None),
          "simulated": True, "worker_role": "fake-combo-worker",
          "drill": bool(getattr(args, "drill", False)),
          "drill_thresholds": drill_rec if getattr(args, "drill", False) else None,
          "drill_note": DRILL_NOTE if getattr(args, "drill", False) else None,
          "model_sha256": sha256_file(MODEL), "script_sha256": sha256_file(SELF),
          "server_lifecycle_size": SERVER_LIFECYCLE_SIZE,
          "attended_operation": ATTENDED_OPERATION,
          "sampler_pid": None if fixed else sampler.pid,
          "worker_pid": None if fixed else os.getpid(),
          "pid_redacted_for_determinism": bool(fixed),
          "sampler_returncode": sampler_rc,
          "sampler_samples_expected": n_samples,
          "rows": rows, "rows_artifact_sha256": art,
          "resource_summary": summary,
          "pass_conditions": {"simulated_wiring_ok": sampler_rc == 0,
                              "timeline_present": (child_dir / "resource_timeline.jsonl").is_file()},
          "status": "pass" if sampler_rc == 0 else "fail_or_limited",
          "written_at": clk(), "finalized_at": clk()}
    r = atomic_write_json(child_dir / "checkpoint.json", ck)
    set_state(stage="closed", stop=True, port_closed_within_30s=True)
    # T14 确定性化（父 agent 2026-09-15 裁定 A）：**必须在宣告 closed 之后驻留**，
    # 否则 supervisor 的 `while proc.poll() is None` 轮询可能永远看不到"已收尾但仍在"
    # 的窗口 ⇒ 正常收尾记录写不写变成随机 ⇒ T14 逐字节断言摇摆。真 worker 因要拆
    # sampler/COMSOL 天然驻留，故此处驻留也是**保真度**修正，而非仅为让测试好过。
    if fixed and r.get("ok"):
        time.sleep(FAKE_CLOSED_LINGER_S)
    return 0 if r.get("ok") else 1


def run_combo_worker(args) -> int:
    # ⚠️ `import mph` **只在本 combo-worker 分支内执行**；supervisor 与 --dry-run 角色
    # **永不加载 mph**（故 dry-run 报告里 `mph_imported` 恒为 False）。
    # 文件级 grep 会看到这一行——请勿据此认为 supervisor 依赖 mph。
    import numpy as np
    import mph

    rd = RUNS / args.run_id
    x, n1 = args.combo
    idx = args.child_index
    attempt = getattr(args, "attempt", 1)
    # F1 修复：worker 侧必须用**唯一阈值裁定点**（与 supervisor/sampler 同源），
    # 否则 checkpoint 的 thresholds / summarize_timeline / combo_pass_conditions 会用默认值，
    # 而实际执行时生效的是演练覆盖值（实测 r3c 之后的演练：记 12288 而生效 5000）。
    # 生产路径（无 --drill）下 resolve_thresholds 返回的就是默认值 ⇒ **数值逐项不变**。
    th, th_rec = resolve_thresholds(args)
    freqs = list(args.freqs)

    # ---- P0-2：child/attempt 证据隔离目录 ----
    # 本 worker 只写自己的 child 目录；**不删除、不复用、不覆盖**任何既有 child 的证据。
    child_dir = rd / CHILD_DIR_FMT.format(idx=idx, attempt=attempt)
    if child_dir.exists() and any(child_dir.iterdir()):
        atomic_write_json(rd / f"{child_dir.name}_refused.json",
                          {"at": now_iso(), "reason": "child_dir_exists_nonempty",
                           "child_dir": str(child_dir),
                           "note": "拒绝复用非空 child 目录（append-only）"})
        return 1
    child_dir.mkdir(parents=True, exist_ok=True)

    worker_f = child_dir / WORKER_STATE_NAME
    jsonl_f = child_dir / "resource_timeline.jsonl"

    def set_state(**kw):
        """本进程是 worker_state.json 的**唯一写入者**（§7.3 单写者，无跨进程竞争）。"""
        cur = read_worker_state(child_dir)
        cur.update(kw)
        cur["writer"] = "lt2_combo_worker"
        return write_own_state(worker_f, cur)

    set_state(pid=None, combo=f"({x},{n1})", stage="startup", stop=False,
              cancel_requested=False, worker_pid=os.getpid(), child_index=idx,
              attempt=attempt, child_dir=str(child_dir), simulated=False,
              server_identity=None, pid_source=None)

    sampler = None
    try:
        sampler = subprocess.Popen(sampler_cmd_for(args, child_dir, args.run_id),
                                   stdout=DEVNULL, stderr=DEVNULL)
        set_state(sampler_pid=sampler.pid)
    except Exception as exc:
        atomic_write_json(child_dir / "worker_error.json",
                          {"at": now_iso(), "stage": "sidecar_spawn",
                           "error": f"{type(exc).__name__}: {exc}", "combo": [x, int(n1)]})
        return 1

    client = None
    pid = None
    identity = None
    cancel_rec: dict | None = None
    stop_wd = threading.Event()
    wd_state: dict = {"fired": False}

    def watchdog():
        """§7.1 修正：watchdog **不再触碰 MPh client**（无法证明跨线程安全）。

        只做两件事：读 sampler_state 的实时 verdict；把 cancel_requested 写进 worker_state。
        真正的终止由 supervisor 的 `verified_emergency_termination` 执行；
        若 study 自行返回，主线程看到 cancel_requested 后走同线程的清理。
        """
        while not stop_wd.is_set():
            try:
                ss = read_sampler_state(child_dir)
                alive = bool(sampler and sampler.poll() is None)
                health = sidecar_health(time.time(), ss.get("last_sample_ts"), alive)
                ws = read_worker_state(child_dir)
                action = decide_next_action({"verdict": ss.get("verdict", "ok")},
                                            health, ws)
                if action["action"] == "hard_stop_enforce" and not wd_state["fired"]:
                    wd_state["fired"] = True
                    wd_state["action"] = action
                    set_state(cancel_requested=True, cancel_reason=action.get("reason"),
                              cancel_source=action.get("source"),
                              cancel_requested_at=now_iso())
            except Exception:
                pass
            stop_wd.wait(args.gate_poll)

    try:
        client = mph.start(cores=1, port=PORT)
        # §7.4：**优先**用监听端口直接取 PID，而不是启发式
        sp = server_pid_from_port(timeout_s=30)
        pid = sp.get("pid")
        identity = proc_identity(pid)
        if identity is not None:
            identity["worker_pid"] = os.getpid()
            identity["parent_is_worker"] = (identity.get("parent_pid") == os.getpid())
        set_state(pid=pid, server_identity=identity, pid_source=sp.get("source"),
                  pid_source_waited_s=sp.get("waited_s"), pid_source_note=sp.get("note"))

        wd = threading.Thread(target=watchdog, daemon=True)
        wd.start()

        model = client.load(str(MODEL))
        java = model.java
        comp = java.modelNode("comp1")
        geom, mesh = comp.geom("geom1"), comp.mesh("mesh1")
        for tag in ("param", "param2"):
            try:
                java.study("std1").feature(tag).active(False)
            except Exception:
                pass
        java.study("std1").feature("freq").set("plist", " ".join(f + "[MHz]" for f in freqs))
        java.param().set("x_scale", f"{x:g}")
        java.param().set("N_w_te1", str(int(n1)))

        set_state(stage="geometry")
        geom.run()
        set_state(stage="mesh")
        mesh.run()
        try:
            nel = int(mesh.getNumElem())
        except Exception:
            nel = None

        set_state(stage="lt2c_gate")
        try:
            lt2c = lt2c_quick_gate(java, comp, geom, x, n1)
        except Exception as exc:
            lt2c = {"checks": {"pass": False},
                    "detail": {"lt2c_error": f"{type(exc).__name__}: {exc}"}}

        rows: list[dict] = []
        solve_s = None
        solve_error = None
        if not wd_state["fired"] and lt2c["checks"].get("pass"):
            set_state(stage="solve", solve_started_at=now_iso())
            t0 = time.perf_counter()
            try:
                java.study("std1").run()
            except Exception as exc:
                solve_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            solve_s = round(time.perf_counter() - t0, 1)
            set_state(solve_returned_at=now_iso(), solve_seconds=solve_s,
                      solve_error=solve_error)

        # 硬停已触发：本进程**不**跨线程碰 client（§7.1）。
        # 若 study 已自行返回，就在同线程做一次正常清理；否则由 supervisor 执行
        # verified_emergency_termination。
        if wd_state["fired"]:
            cancel_rec = {"trigger": wd_state.get("action"),
                          "naming_note": ("worker 侧只记录触发；终止由 supervisor 的 "
                                          "verified_emergency_termination 执行")}
            if solve_error is None and solve_s is not None:
                try:
                    client.clear()
                    cancel_rec["worker_same_thread_cleanup"] = "clear_ok"
                except Exception as exc:
                    cancel_rec["worker_same_thread_cleanup"] = f"clear_failed: {type(exc).__name__}"
                try:
                    client.disconnect()
                except Exception:
                    pass

        if solve_error is None and not wd_state["fired"] and lt2c["checks"].get("pass"):
            set_state(stage="postprocess")     # ← D-D 修复：原为 set_state(state_f, ...) 遗留引用

            def cx(expr, i):
                try:
                    r = float(np.asarray(model.evaluate("real(" + expr + ")", inner=[i]),
                                         dtype=float).ravel()[0])
                    m = float(np.asarray(model.evaluate("imag(" + expr + ")", inner=[i]),
                                         dtype=float).ravel()[0])
                    return r, m
                except Exception:
                    return None, None

            def freq_of(i):
                return float(np.asarray(model.evaluate("freq", inner=[i]),
                                        dtype=float).ravel()[0])

            rows = extract_rows(freqs, cx, freq_of, x, n1, nel, solve_s)

        # ---- checkpoint：**先原子写，再关 server**；全部落在 child 目录内 ----
        # 收尾逻辑与测试共用 finalize_after_solve()（D-D：抽出来才测得到）
        ck = finalize_after_solve(
            run_id=args.run_id, idx=idx, attempt=attempt, child_dir=child_dir,
            x=x, n1=n1, freqs=freqs, rows=rows, lt2c=lt2c, th=th,
            cancel_rec=cancel_rec, set_state=set_state, jsonl_f=jsonl_f,
            clock=(_fixed_clock if getattr(args, "fixed_timestamps", False) else None),
            meta={"server_pid": pid, "server_identity": identity,
                  "pid_source": sp.get("source"),
                  "pid_source_waited_s": sp.get("waited_s"),
                  "sampler_pid": getattr(sampler, "pid", None),
                  # ③ 解析留痕（child 级可见「CLI 原文 → 解析出的频率列表/条数」）
                  # ② 本 child 所属 freeze id（核验结果只在批次根 batch_manifest.json）
                  "freqs_parse": getattr(args, "freqs_parse", None),
                  "freeze_id": getattr(args, "freeze_id", None),
                  # F1：checkpoint 的 `thresholds` 已由 th（生效值）给出，这里只补**来源**，
                  # 单源不重复：defaults/overrides/effective 只此一处（不再往 pass_conditions 里塞副本）
                  "thresholds_provenance": th_rec,
                  "drill": bool(getattr(args, "drill", False)),
                  "drill_thresholds": (th_rec if getattr(args, "drill", False) else None),
                  "drill_note": DRILL_NOTE if getattr(args, "drill", False) else None})
        return 0
    except Exception as exc:
        # D-D：错误记录必须带**出错时所在阶段**与异常类型，否则分类只能靠猜
        stage_at_error = None
        try:
            stage_at_error = read_worker_state(child_dir).get("stage")
        except Exception:
            pass
        try:
            atomic_write_json(child_dir / "worker_error.json",
                              {"at": now_iso(), "error": f"{type(exc).__name__}: {exc}",
                               "error_type": type(exc).__name__,
                               "stage_at_error": stage_at_error,
                               "combo": [x, int(n1)], "child_index": idx, "attempt": attempt,
                               "note": "worker 自身抛出的异常（代码/环境问题），非资源硬停"})
        except Exception:
            pass
        print(f"[worker] 异常: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        stop_wd.set()
        try:
            set_state(stage="cleanup")
        except Exception:
            pass
        if client is not None and not wd_state["fired"]:
            try:
                client.clear()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass
        closed = False
        for _ in range(PORT_CLOSE_WAIT_S):
            if not port_open():
                closed = True
                break
            time.sleep(1)
        try:
            set_state(stage="closed", stop=True, port_closed_within_30s=closed)
        except Exception:
            pass
        try:
            if sampler is not None:
                sampler.wait(timeout=20)
                sampler_rc = sampler.returncode
            else:
                sampler_rc = "not_started"
        except Exception:
            sampler.kill()
            sampler_rc = "killed"
        # 收尾信息补写（checkpoint 已先落盘，这里只补运行时收尾字段）
        try:
            p = child_dir / "checkpoint.json"
            d = read_json_safe(p)
            if d:
                d["port_closed_within_30s"] = closed
                d["port_open_at_end"] = port_open()
                d["sampler_returncode"] = sampler_rc
                cp = d.get("pass_conditions", {})
                cp["server_cleanup_ok"] = closed and not port_open()
                cp["sampler_exit_ok"] = (sampler_rc == 0)
                cp_ok, cp_violations = all_conditions_true(cp)
                d["pass_conditions"] = cp
                d["pass_condition_shape_violations"] = cp_violations
                d["status"] = "pass" if cp_ok else "fail_or_limited"
                d["finalized_at"] = now_iso()
                atomic_write_json(p, d)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# supervisor
# --------------------------------------------------------------------------- #
def classify_comsol_processes(procs: list[dict]) -> dict:
    """把 COMSOL 家族进程分成「阻断项」与「允许的 GUI」。

    **纯函数** ⇒ 可被第三方用合成清单复核（不需真机进程）。规则：
      · `COMSOL_BLOCKING_PROCS`（mphserver / batch / compile）在场 ⇒ 阻断（gate_pass=False）；
      · `COMSOL_GUI_ALLOWED`（ComsolUI，用户 GUI）在场 ⇒ **允许**，但单独记录并在报告中声明；
      · 其它名字含 comsol 的进程 ⇒ 归入 `other_comsol_like_processes`（如实登记，不阻断、不隐藏）。
    """
    blk = {n.lower() for n in COMSOL_BLOCKING_PROCS}
    gui = {n.lower() for n in COMSOL_GUI_ALLOWED}
    blocking = [p for p in procs if str(p.get("name", "")).lower() in blk]
    gui_p = [p for p in procs if str(p.get("name", "")).lower() in gui]
    other = [p for p in procs if p not in blocking and p not in gui_p]
    return {"blocking_processes": blocking, "allowed_gui_processes": gui_p,
            "other_comsol_like_processes": other,
            "blocking_names": list(COMSOL_BLOCKING_PROCS),
            "gui_allowed_names": list(COMSOL_GUI_ALLOWED),
            "blocking_count": len(blocking), "allowed_gui_count": len(gui_p),
            "clean": len(blocking) == 0,
            "note": ("阻断项在场即拒绝启动；ComsolUI（用户 GUI）在场**允许**但不参与放行，"
                     "仅记录并在报告中声明")}


def comsol_process_scan() -> dict:
    """只读扫描 COMSOL 家族进程，记录 pid / name / start（供第三方复核"开跑时环境是否干净"）。"""
    script = ("Get-Process -ErrorAction SilentlyContinue | "
              "Where-Object { $_.ProcessName -like '*comsol*' } | "
              "ForEach-Object { '{0}|{1}|{2}' -f $_.Id, $_.ProcessName, "
              "[int][double]::Parse((Get-Date $_.StartTime -UFormat %s)) }")
    out = run_ps(script, timeout=25)
    procs: list[dict] = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.strip().split("|")]
        if len(parts) >= 3 and parts[0].isdigit():
            try:
                ep = int(float(parts[2]))
            except Exception:  # noqa: BLE001
                ep = None
            procs.append({"pid": int(parts[0]), "name": parts[1], "start_epoch": ep,
                          "start_iso": (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ep))
                                        if ep else None)})
    rec = {"method": ("Get-Process | Where-Object ProcessName -like '*comsol*'"
                      "（只读；逐项记录 pid / name / start）"),
           "read_only": True, "comsol_family_all": procs}
    rec.update(classify_comsol_processes(procs))
    return rec


def preflight(avail_gate: float = PREFLIGHT_AVAIL_MB,
              commit_gate: float = PREFLIGHT_COMMIT_MB) -> dict:
    """只读探测：端口 / COMSOL 家族进程 / 内存与 commit。**不启动 COMSOL**。

    **开跑前连测两次**（间隔 `PREFLIGHT_DOUBLE_SAMPLE_GAP_S`）：两次**都**满足才算 `gate_pass`。
    依据（r3e 实测）：外部消费者可在 5 秒内阶跃吃掉 ~6 GB commit ⇒ 单次采样不足。
    顶层 `system_available_physical_mb` / `commit_available_mb` / `port_free` / `other_server_pid`
    是 **sample1** 的值（保持既有读者兼容）；两次的完整数据在 `double_sample` 里（单一事实来源）。
    """
    s1 = {"at": now_iso(), **sysmem(), "port_free": not port_open()}
    scan1 = comsol_process_scan()
    time.sleep(PREFLIGHT_DOUBLE_SAMPLE_GAP_S)
    s2 = {"at": now_iso(), **sysmem(), "port_free": not port_open()}
    scan2 = comsol_process_scan()

    def _ok(s: dict, scan: dict) -> bool:
        return bool(s["port_free"] and scan.get("clean")
                    and s["system_available_physical_mb"] >= avail_gate
                    and s["commit_available_mb"] >= commit_gate)

    blocked_by = []
    for tag, s, scan in (("sample1", s1, scan1), ("sample2", s2, scan2)):
        if not s["port_free"]:
            blocked_by.append(f"{tag}:port_not_free")
        if not scan.get("clean"):
            blocked_by.append(f"{tag}:comsol_blocking_processes="
                              f"{[p.get('name') for p in scan.get('blocking_processes') or []]}")
        if s["system_available_physical_mb"] < avail_gate:
            blocked_by.append(f"{tag}:avail {s['system_available_physical_mb']} < {avail_gate}")
        if s["commit_available_mb"] < commit_gate:
            blocked_by.append(f"{tag}:commit {s['commit_available_mb']} < {commit_gate}")

    other_server_pid = next((p["pid"] for p in (scan1.get("blocking_processes") or [])
                             if str(p.get("name", "")).lower() == "comsolmphserver"), None)
    pre = {
        "at": s1["at"], "at_second_sample": s2["at"],
        "port_free": s1["port_free"], "port_free_second_sample": s2["port_free"],
        "other_server_pid": other_server_pid,
        "system_available_physical_mb": s1["system_available_physical_mb"],
        "commit_available_mb": s1["commit_available_mb"],
        "system_memory_load_percent": s1.get("system_memory_load_percent"),
        "double_sample": {"gap_s": PREFLIGHT_DOUBLE_SAMPLE_GAP_S,
                          "sample1": s1, "sample2": s2,
                          "delta": {"system_available_physical_mb": round(
                              s2["system_available_physical_mb"]
                              - s1["system_available_physical_mb"], 1),
                              "commit_available_mb": round(
                                  s2["commit_available_mb"] - s1["commit_available_mb"], 1)},
                          "note": ("两次都必须过门禁；本项用于发现「开跑前就已在消耗内存」的外部消费者")},
        "comsol_process_scan": scan1, "comsol_process_scan_second_sample": scan2,
        "gates": {"physical_avail_gate_mb": avail_gate, "commit_gate_mb": commit_gate},
        "gate_defaults": {"physical_avail_gate_mb": PREFLIGHT_AVAIL_MB,
                          "commit_gate_mb": PREFLIGHT_COMMIT_MB},
        "gate_overridden": bool(avail_gate != PREFLIGHT_AVAIL_MB
                                or commit_gate != PREFLIGHT_COMMIT_MB),
    }
    pre["gate_pass"] = bool(_ok(s1, scan1) and _ok(s2, scan2))
    pre["blocked_by"] = blocked_by
    return pre


def _set_blocked(result: dict, reason: str, *, retry_class: str | None = None,
                 retry_reason: str | None = None, auto_retry_attempted: bool = False) -> None:
    """写批次阻塞：**把两件事分开**（父 agent 2026-09-15 裁定 ③）。

    · `blocked_reason` —— **什么失败了**（只讲事实，不夹重跑分类）；
    · `retry_class` / `retry_reason` —— **为何不重跑**（分类与人类可读理由）；
    · `auto_retry_attempted` —— 本次是否真的自动重跑过（与"分类器建议重跑"是两件事）。

    背景：旧写法把状态与重跑分类粘成一句
    （`child_00_not_pass:fail_or_limited（不可自动重跑：normal_completion）`），
    读起来像"因为正常完成所以失败"——这正是"记录名与实际语义不一致"的一族。
    """
    result["blocked_reason"] = reason
    result["retry_class"] = retry_class
    result["retry_reason"] = retry_reason
    result["auto_retry_attempted"] = bool(auto_retry_attempted)


def classify_retry(child: dict) -> dict:
    """§6 重跑分类：**只有可判定为瞬态**的失败允许自动重跑一次。

    不得自动重跑：资源硬停 / LT2-C 失败 / 哈希漂移 / checkpoint 问题 /
    端口归属未知或属他进程 / sampler-supervisor 完整性失败。
    """
    pc = child.get("pass_conditions") or {}
    lt2c = child.get("lt2c_quick_gate") or {}
    lt2c_pass = (lt2c.get("checks") or {}).get("pass")
    trig = child.get("termination_trigger") or {}
    # 正常收尾记录**单独**放 normal_completion（不得塞进 termination_trigger：T12 明确要求
    # 正常路径的 termination_trigger 为 None）⇒ 这里把两种来源的 trigger_kind 合起来看。
    nc = child.get("normal_completion") or {}
    tk = trig.get("trigger_kind") or nc.get("trigger_kind")
    is_hs = trig.get("is_hard_stop") is True

    # ---- D-B 修复：resource_hard_stop **只**在真的出了越线样本时才成立 ----
    # 旧代码只要有 termination_trigger 就判 resource_hard_stop，会把「worker 没起来」
    # 「目录复用被拒」「sampler 首个样本前退出」这些基础设施故障伪装成资源问题。
    if is_hs and tk == "threshold_crossed":
        if child.get("drill"):
            return {"retry": False, "class": "drill_hard_stop",
                    "reason": "演练阈值越线（drill）——不计入生产资源事件，不自动重跑"}
        return {"retry": False, "class": "resource_hard_stop",
                "reason": "真实阈值连续越线，资源硬停不得自动重跑（§6）"}
    if child.get("child_dir_reuse_refused"):
        return {"retry": False, "class": "child_dir_reuse_refused",
                "reason": "worker 因 child 目录非空而拒绝复用（append-only 保护）⇒ fail-closed"}
    # 正常收尾（裁定：正常完成守卫）——**不是失败**，因此不得落进 unclassified / integrity 桶
    if tk == TRIGGER_KIND_NORMAL_COMPLETION:
        return {"retry": False, "class": "normal_completion",
                "reason": ("正常收尾：worker 已产出 checkpoint / 已宣告 stage=closed 之后 "
                           "sidecar 自然退出，未发生 force enforce，不涉及重跑")}
    if tk == "worker_startup_failure":
        return {"retry": True, "class": "server_startup_transient",
                "reason": f"worker 启动瞬态失败（{trig.get('reason')}）⇒ 允许重跑一次"}
    if tk in ("integrity_failure", "sample_gap_or_health", "unclassified_failure"):
        return {"retry": False, "class": "sampler_supervisor_integrity",
                "reason": f"非资源性故障（trigger_kind={tk}）：{trig.get('reason')}"}

    # D-D(3)：worker **自身**抛异常（如 NameError）是代码/环境 bug，独立分类，
    # 不要指向「监控完整性」子系统——那会让人查错方向（真机 run 就发生过）。
    werr = child.get("worker_error")
    if werr:
        etype = child.get("worker_error_type") or ""
        stage_err = child.get("worker_error_stage")
        postsolve = (stage_err in ("postprocess", "checkpoint")
                     or etype in ("NameError", "AttributeError", "TypeError",
                                  "UnboundLocalError", "KeyError", "IndexError"))
        cls = "worker_exception_postsolve" if postsolve else "worker_exception_presolve"
        return {"retry": False, "class": cls,
                "reason": (f"worker 自身异常（{etype or '未知类型'} @ 阶段 {stage_err}）："
                           f"{str(werr)[:160]} ⇒ 代码/环境 bug，非资源硬停、非监控完整性故障")}
    if lt2c_pass is False:
        return {"retry": False, "class": "lt2c_gate_failure",
                "reason": "LT2-C 几何/选择/控制面门禁失败不得自动重跑（§6）"}
    if child.get("hash_drift") or child.get("hash_drift_detected"):
        return {"retry": False, "class": "hash_drift",
                "reason": "模型/脚本/判据/扫描哈希漂移不得自动重跑（§6）"}
    if child.get("checkpoint_problem"):
        return {"retry": False, "class": "checkpoint_problem",
                "reason": "checkpoint 重复/损坏/越界键不得自动重跑（§6）"}
    if child.get("ownership_unknown_or_other"):
        return {"retry": False, "class": "port_ownership",
                "reason": "端口归属未知或属他进程不得自动重跑（§6）"}
    if child.get("sampler_integrity_failure"):
        return {"retry": False, "class": "sampler_supervisor_integrity",
                "reason": "sampler/supervisor 完整性失败不得自动重跑（§6）"}

    # ---- 以下判为瞬态，允许一次重跑 ----
    stage = child.get("failure_stage")
    err = str(child.get("solve_error") or child.get("worker_error") or "")
    if child.get("pid_source") == "none" or stage in ("startup", "loading", "sidecar_spawn"):
        return {"retry": True, "class": "server_startup_transient",
                "reason": f"启动瞬态失败（stage={stage}, pid_source={child.get('pid_source')}）"}
    if err and pc.get("commit_hard_stop_samples_0") is not False:
        return {"retry": True, "class": "solver_exception_transient",
                "reason": f"求解异常且不伴随 LT2-C/哈希/资源违规：{err[:160]}"}
    if child.get("port_cleanup_timeout_after_verified_cleanup"):
        return {"retry": True, "class": "port_cleanup_timeout",
                "reason": "归属已核验且清理完成后的端口清理超时"}
    return {"retry": False, "class": "unclassified",
            "reason": "无法判定为瞬态 ⇒ 不自动重跑（fail-closed）"}


def supervise_child(run_id: str, idx: int, x: float, n1: int, args, attempt: int = 1) -> dict:
    """拉起 combo-worker 并**实时监督**（§7.1：读 verdict/reasons/cancel_requested，不等 stale）。"""
    rd = RUNS / run_id
    child_dir = rd / CHILD_DIR_FMT.format(idx=idx, attempt=attempt)
    child_dir.mkdir(parents=True, exist_ok=True)
    termination_rec: dict | None = None
    trigger: dict | None = None
    worker_role = getattr(args, "worker_role", "combo-worker")
    _fparse = getattr(args, "freqs_parse", None) or {}
    _expect = _fparse.get("expected_count", len(args.freqs))
    cmd = [sys.executable, str(SELF), "--role", worker_role, "--run-id", run_id,
           "--combo", json.dumps([x, n1]), "--child-index", str(idx),
           "--attempt", str(attempt),
           # ③ 期望条数必须一并下传：否则 worker 会用默认生产口径（7）重判，
           # 非生产点数（如 --expect-freq-count 3）会在 worker 侧被误拒。
           "--freqs", ",".join(args.freqs), "--expect-freq-count", str(_expect),
           "--interval", str(args.interval),
           "--gate-poll", str(args.gate_poll)]
    if getattr(args, "freeze_id", None):
        cmd += ["--freeze-id", str(args.freeze_id)]
    if getattr(args, "drill", False):
        cmd += ["--drill"]
        # 阈值覆盖必须一并传给 worker，否则 worker→sampler 会退回默认阈值（实测踩到）
        for k, flag in (("ws_hard_stop_mb", "--ws-hard-stop-mb"),
                        ("commit_hard_stop_mb", "--commit-hard-stop-mb"),
                        ("physical_hard_stop_mb", "--physical-hard-stop-mb")):
            v = getattr(args, k, None)
            if v is not None:
                cmd += [flag, str(v)]
    if getattr(args, "fixed_timestamps", False):
        cmd += ["--fixed-timestamps"]
    proc = subprocess.Popen(cmd, stdout=DEVNULL, stderr=DEVNULL)
    eff_th, _eff_rec = resolve_thresholds(args)
    det = bool(getattr(args, "fixed_timestamps", False))
    det_clock = _fixed_clock if det else None
    enforced = False
    enforcement_source = None
    # 正常收尾记录（裁定：正常完成守卫）。记录只写一次；**抑制 enforce 则持续到 worker 退出**
    # 或超过 NORMAL_COMPLETION_GRACE_S（有界，见循环内注释）。
    normal_completion_rec: dict | None = None
    normal_completion_since: float | None = None
    started_at = time.time()
    while proc.poll() is None:
        ws = read_worker_state(child_dir)
        ss = read_sampler_state(child_dir)
        now = time.time()
        in_startup = (now - started_at) < STARTUP_GRACE_S

        # ---- 正常完成守卫（父 agent 2026-09-14 裁定；r3/r3b 实测）----
        # 实测：worker 写完 checkpoint 并置 stage=closed/stop=true 之后、进程退出之前，
        # sampler 已由 worker 自己正常停掉 ⇒ 旧代码看到 sidecar_exited 后误走 enforce，
        # 于是一次**正常收尾**留下 hard_stop_enforce 触发记录 + signals 文件，
        # 且因 enforced=True 跳过 proc.wait(30) ⇒ worker_returncode 丢成 null。
        # 判据只用**正常完成的正面证据**（两者都只在求解收尾之后才可能出现）：
        #   stage == "closed"（worker 已宣告收尾完成） 或 checkpoint.json 已存在。
        # 附加 `verdict != hard_stop`：真实越线永远优先，绝不被降级为「正常收尾」。
        # 未命中守卫时行为**完全不变**（真硬停发生在 solve 期间，两者都不满足 ⇒ 照常 enforce）。
        #
        # ⚠️ r3c 实测缺陷（**必须持续抑制，不能只抑制一次**）：第一版把"只记一次"写进了守卫条件
        # （`normal_completion_rec is None`），于是记录之后的下一轮轮询就**落到旧判定路径**、
        # 看到 sidecar_exited 再次 enforce —— r3c 里 20:12:30 记了正常收尾、
        # 20:12:37 又 enforce（signals + 终止记录照旧出现）。现在改为：
        #   守卫成立期间**每轮都抑制** enforce（只写一次记录），
        #   但设**有界**上界 NORMAL_COMPLETION_GRACE_S，超过即升级处置（否则 worker 卡死时
        #   supervisor 会永久阻塞 —— 这是"持续抑制"必须付的代价，必须显式封顶）。
        _done_markers = []
        if ws.get("stage") == "closed":
            _done_markers.append("worker_stage_closed")
        if (child_dir / "checkpoint.json").is_file():
            _done_markers.append("checkpoint_present")
        _guard_active = bool(_done_markers) and ss.get("verdict") != "hard_stop"
        if _guard_active:
            if normal_completion_rec is None:
                _nc_action = {"action": "observe_normal_completion",
                              "source": "normal_completion_guard", "reason": _done_markers,
                              "note": ("正常收尾：不 enforce、不写 signals（没有终止要求）；"
                                       "等 worker 自然退出以取得**真实** worker_returncode")}
                normal_completion_rec = classify_trigger(
                    ss, ws, _nc_action, eff_th, clock=det_clock, redact=det)
                # 文件名与语义一致（裁定 B）：正常收尾写 COMPLETION_FILE_NAME，
                # **不写** TRIGGER_FILE_NAME（后者专表"发生过终止动作/资源事件"）。
                atomic_write_json(child_dir / COMPLETION_FILE_NAME, normal_completion_rec)
                normal_completion_since = now
            _waited = now - (normal_completion_since or now)
            if _waited <= NORMAL_COMPLETION_GRACE_S:
                time.sleep(args.gate_poll)
                continue
            # 有界升级：正常收尾已判定但 worker 迟迟不退出 ⇒ 升级处置，避免永久阻塞
            action = {"action": "hard_stop_enforce", "source": "normal_completion_timeout",
                      "reason": [f"正常收尾已判定（{_done_markers}），但 worker 在 "
                                 f"{NORMAL_COMPLETION_GRACE_S:g}s 内仍未退出"
                                 f"（已等 {_waited:.1f}s）⇒ 升级处置"]}
            trigger = classify_trigger(ss, ws, action, eff_th, clock=det_clock, redact=det)
            enforcement_source = action["source"]
        elif not ws.get("sampler_pid"):
            # D-A 修复：启动宽限期内**不得**因为"还没有 sampler_pid / 还没有样本"就判 sidecar 失效。
            # 旧代码首轮 ws={} → proc_exists(None)=False → sidecar_health 报 sidecar_exited
            # → 立即终止 → 往 child 目录写信号 → worker 的"非空即拒绝"守卫把它挡死（阻断级回归）。
            if in_startup:
                time.sleep(args.gate_poll)
                continue
            action = {"action": "hard_stop_enforce", "source": "worker_startup_timeout",
                      "reason": [f"worker 在 {STARTUP_GRACE_S}s 内未登记 sampler_pid"]}
            trigger = classify_trigger(ss, ws, action, eff_th, clock=det_clock, redact=det)
            enforcement_source = action["source"]
        else:
            alive = proc_exists(ws.get("sampler_pid"))
            health = sidecar_health(now, ss.get("last_sample_ts"), alive)
            if (health.get("verdict") == "hard_stop" and ss.get("last_sample_ts") is None
                    and in_startup):
                time.sleep(args.gate_poll)
                continue
            action = decide_next_action({"verdict": ss.get("verdict", "ok")}, health, ws)
            if action["action"] != "hard_stop_enforce":
                time.sleep(args.gate_poll)
                continue
            trigger = classify_trigger(ss, ws, action, eff_th, clock=det_clock, redact=det)
            enforcement_source = action.get("source")

        if trigger is not None:
            # 裁定 3：把「谁要求终止」写进触发记录本身（演练 vs 资源一眼可辨）。
            # 必须在 verified_emergency_termination 之前赋值：它会把 trigger 原样写进
            # termination_trigger.json（save_trigger_record 步骤）。
            trigger["enforced_by"] = classify_enforced_by(
                action.get("source"), trigger.get("trigger_kind"),
                bool(getattr(args, "drill", False)))
            trigger["is_drill_run"] = bool(getattr(args, "drill", False))
            trigger["enforced_by_definition"] = ENFORCED_BY_DEFINITION
            termination_rec = verified_emergency_termination(
                child_dir=child_dir, expected_pid=ws.get("pid"),
                identity_at_launch=ws.get("server_identity"), run_id=run_id,
                trigger=trigger, worker_pid=proc.pid,
                clock=det_clock, redact=det)
            enforced = True
            break
        time.sleep(args.gate_poll)
    if not enforced:
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()
    else:
        # enforce 路径：不阻塞主流程，但**短暂有界**等待以便拿到 worker 的真实退出码。
        # 父 agent 裁定 ①：`worker_returncode` 不得因 enforced 而为 null（旧行为即如此）。
        # rc 只用于 `status` 兜底字符串，不参与任何判定；拿不到就如实留 null（不编造）。
        try:
            proc.wait(timeout=ENFORCE_WORKER_WAIT_S)
        except Exception:
            pass
    rc = proc.returncode
    ck = read_json_safe(child_dir / "checkpoint.json")
    err = read_json_safe(child_dir / "worker_error.json")
    ws_final = read_worker_state(child_dir)
    status = ck.get("status") if ck else None
    res = {"child_index": idx, "attempt": attempt, "combo": [x, int(n1)],
           "child_dir": str(child_dir), "worker_pid": proc.pid,
           "worker_returncode": rc, "checkpoint_present": bool(ck),
           "status": status or ("worker_failed" if rc != 0 else "no_checkpoint"),
           "checkpoint_sha256": sha256_file(child_dir / "checkpoint.json"),
           "pass_conditions": ck.get("pass_conditions"),
           "blocks_next_combination": ck.get("blocks_next_combination"),
           "cancel_record": ck.get("cancel_record"),
           "lt2c_quick_gate": ck.get("lt2c_quick_gate"),
           "tolerance_evidence": ck.get("tolerance_evidence"),
           "solve_error": ck.get("solve_error"),
           "pid_source": ck.get("pid_source") or ws_final.get("pid_source"),
           "server_pid": ws_final.get("pid"),
           "termination_trigger": trigger,
           "termination": termination_rec,
           "enforcement_source": enforcement_source,
           # 裁定 3：谁要求终止（未 enforce 时为 None）；以及正常收尾记录（未命中守卫时为 None）
           "enforced_by": (termination_rec or {}).get("enforced_by"),
           "normal_completion": normal_completion_rec,
           "worker_returncode_recorded": rc is not None,
           "drill": bool(getattr(args, "drill", False)),
           "worker_error": (err or {}).get("error") or None,
           "worker_error_type": (err or {}).get("error_type"),
           "worker_error_stage": (err or {}).get("stage_at_error"),
           "failure_stage": ws_final.get("stage"),
           "sampler_integrity_failure": bool(
               ws_final.get("sampler_pid") and not proc_exists(ws_final.get("sampler_pid"))
               and not ck),
           "child_dir_reuse_refused": (rd / f"{child_dir.name}{REFUSED_FILE_SUFFIX}").is_file(),
           "timeline_present": (child_dir / "resource_timeline.jsonl").is_file(),
           "timeline_sha256": sha256_file(child_dir / "resource_timeline.jsonl"),
           "sampler_state_sha256": sha256_file(child_dir / SAMPLER_STATE_NAME),
           "worker_state_sha256": sha256_file(child_dir / WORKER_STATE_NAME)}
    res["retry_classification"] = classify_retry(res)
    return res


# --------------------------------------------------------------------------- #
# child 目录清单规约 + 聚合 manifest 组装（§7.2 的"批次根只写聚合 manifest"）
#
# 背景（父 agent 实测 G2/G3）：此前 `batch_manifest.json` 在自测里**从未产出**，
# 且报告只列了前 4 个 child 目录、掩盖了另外 4 个形态不齐的目录。
# 这里把"每个 child 目录应当包含什么、缺失是否合法"写成显式规约，
# 并提供**只读扫描 + 一次写**的组装入口，使聚合证据可由第三方独立复算。
# --------------------------------------------------------------------------- #
CHILD_REQUIRED_BY_KIND = {
    # 完整求解 attempt（worker 驱动）
    "solve_attempt": ["worker_state.json", "sampler_state.json",
                      "resource_timeline.jsonl", "resource_timeline.csv",
                      "checkpoint.json"],
    # 只跑了 sampler（无求解）——例如 T4 的证据隔离测试
    "sampler_only": ["worker_state.json", "sampler_state.json",
                     "resource_timeline.jsonl", "resource_timeline.csv"],
    # 只做了硬停动作/拒绝终止的探针——本就不该有求解时序
    "enforcement_probe": ["worker_state.json", "termination_trigger.json"],
    # 只写状态（状态竞争测试）
    "state_only": ["worker_state.json"],
}

CHILD_FILE_SPEC = {
    "worker_state.json": "worker 独占写：pid/stage/combo/stop/cancel_requested/server_identity",
    "sampler_state.json": "sidecar 独占写：last_sample_ts/sample_index/verdict/reasons/warnings",
    "resource_timeline.jsonl": "完整事件流（一行一样本，不截断）",
    "resource_timeline.csv": "人读用，列名与 R0 的 COLS 一致",
    "checkpoint.json": "求解 attempt 的原子 checkpoint（含 rows/资源摘要/哈希/容差证据）",
    "rows.csv": "带 source_run_id / source_artifact_sha256 的 7 行结果",
    "raw_rows.csv": "求解原始 7 行（其 sha256 即 source_artifact_sha256 的来源）",
    "termination_trigger.json": "终止动作的触发记录；**必带 trigger_kind**，只有 "
                                "`threshold_crossed` 才算真正的资源硬停",
    "completion_record.json": "**正常收尾**记录（裁定 B 改名）：`trigger_kind="
                              "normal_completion_sidecar_exit`、`is_hard_stop=false`、"
                              "`enforced=false`、`termination_performed=false` ⇒ "
                              "**本次未发生终止**，本文件**不是**终止要求、**不是**资源事件。"
                              "读者判定「有没有终止动作」只看 termination_trigger.json",
    "worker_error.json": "worker 异常留痕（仅异常时存在）",
}
CHILD_FILE_SPEC_NOTE = (
    "**唯一规则**：`child_*/` 只放证据；supervisor 的跨进程信号放在 `<run_id>/signals/`"
    "（`<child_dir_name>.signal.json`），因此 child 目录里**不会**出现 supervisor_signal.json。"
    "缺失是否合法取决于 kind：见 CHILD_REQUIRED_BY_KIND；"
    "`enforcement_probe` 类型本就不该有求解时序（它只验证硬停/拒绝终止路径）。"
)


def parse_child_dir_name(name: str) -> dict:
    """从 `child_00_attempt_1` 解析 idx / attempt（解析失败则字段为 None）。"""
    out = {"child_index": None, "attempt": None}
    try:
        body = name.split("child_", 1)[1]
        idx_s, att_s = body.split("_attempt_", 1)
        out["child_index"] = int(idx_s)
        out["attempt"] = int(att_s)
    except Exception:
        pass
    return out


def describe_child_dir(d: Path) -> dict:
    """如实描述一个 child/attempt 目录：文件清单 + sha256 + kind + 缺失项。"""
    d = Path(d)
    files = {}
    if d.is_dir():
        for f in sorted(d.iterdir()):
            if f.is_file():
                rec = {"bytes": f.stat().st_size, "sha256": sha256_file(f)}
                # 控制通道文件（worker_state.json）天然含真实 sampler_pid/worker pid，
                # 因此它的哈希**不能**进入聚合证据：否则 batch_manifest.json 每次运行都不同
                # （实测：两轮 deterministic manifest 有 1 项差异 = batch_manifest.json）。
                # 这里按生产代码既有先例标记脱敏，而不是给 batch_manifest 开 allowlist 口子。
                if f.name in CONTROL_CHANNEL_FILES:
                    # **bytes 也必须脱敏**：worker_state 含真实 PID，PID 位数变化会改变字节数，
                    # 只脱 sha256 不够（实测：批 manifest 仍两轮不同）。可审计性靠文件名 +
                    # redaction_reason 保保证，而不是靠一个随 PID 漂移的字节数。
                    rec["bytes"] = None
                    rec["sha256"] = None
                    rec["pid_redacted_for_determinism"] = True
                    rec["redaction_reason"] = ("控制通道：含真实 PID/启动时间，bytes 与 sha256 均不参与"
                                              "确定性比对；文件名与原因仍保留以便审计")
                files[f.name] = rec
    present = sorted(files)

    def has(n):
        return n in files

    if has("checkpoint.json"):
        kind = "solve_attempt"
    elif has(TRIGGER_FILE_NAME):
        # **只有**终止触发记录在场才判 enforcement_probe。正常收尾记录
        # （COMPLETION_FILE_NAME）**不**参与该判定：它表示"没发生终止"，不能把目录
        # 归类成"做了硬停动作的探针"（那正是"名字与语义不一致"的另一种形态）。
        kind = "enforcement_probe"
    elif has("resource_timeline.jsonl"):
        kind = "sampler_only"
    else:
        kind = "state_only"
    required = CHILD_REQUIRED_BY_KIND.get(kind, [])
    missing_required = [f for f in required if f not in files]
    return {"child_dir": str(d), "dir_name": d.name, **parse_child_dir_name(d.name),
            "kind": kind, "files": files, "present": present,
            "required_by_kind": required, "missing_required": missing_required,
            "inventory_ok": not missing_required,
            "timeline_sha256": files.get("resource_timeline.jsonl", {}).get("sha256"),
            "checkpoint_sha256": files.get("checkpoint.json", {}).get("sha256"),
            "worker_state_sha256": files.get("worker_state.json", {}).get("sha256"),
            "sampler_state_sha256": files.get("sampler_state.json", {}).get("sha256"),
            "unexpected_files": [f for f in present if f not in CHILD_FILE_SPEC]}


def assemble_manifest_from_child_dirs(run_id: str, extra: dict | None = None,
                                      fixed_at: str | None = None) -> dict:
    """只读扫描 `<run_id>/child_*_attempt_*` 并写批次根 `batch_manifest.json`。

    **不启动 server、不 import mph、不跑 COMSOL**；只读 child 目录 + 一次原子写。
    用于 (a) 故障注入测试产出真实聚合证据、(b) 事后重建已完成批次的聚合清单。
    `fixed_at` 供确定性模式固定 `at` 字段，使 manifest 本身也可复算（G1）。
    """
    rd = RUNS / run_id
    children = [describe_child_dir(d) for d in sorted(rd.glob("child_*_attempt_*")) if d.is_dir()]
    manifest = {
        "run_id": run_id, "role": "manifest-assembly", "at": fixed_at or now_iso(),
        "clock_mode": "fixed" if fixed_at else "wallclock",
        "assembled_read_only": True, "mph_imported": False, "comsol_started": False,
        "child_file_spec": CHILD_FILE_SPEC, "child_file_spec_note": CHILD_FILE_SPEC_NOTE,
        "child_required_by_kind": CHILD_REQUIRED_BY_KIND,
        "child_count": len(children),
        "children_satisfy_inventory": all(c["inventory_ok"] for c in children),
        "children": children,
        # ---- 裁定 3：只读重建 ≠ 一次运行 ----
        # 不伪造冻结证据字段（消费者不得以为这里跑过冻结核验），但必须让消费者能区分
        # 「**没跑过**」与「**跑过但证据缺失**」——故显式声明缺失与其原因。
        "freeze_evidence_complete": False,
        "freeze_evidence_absent_reason": "assembled_read_only_rebuild_not_a_run",
        "freeze_evidence_note": (
            "本 manifest 由 `--assemble-manifest-only` **只读重建**：未执行任何冻结核验，"
            "故 freeze_evidence_complete=false。两个分量 "
            "`freeze_hash_pre_post_match` 与 `executed_from_frozen_snapshot` **故意不写**"
            "（不写 ≠ 判假：它们是「没跑过」，不是「跑过但哈希不符/不是冻结件」）。"
            "要得到这三个布尔，必须真跑一次 supervisor 并显式带 `--freeze-id`。"),
    }
    # 确定性：child_dir 是**绝对路径**，内含 namespace（run1/run2 必然不同）⇒ 两轮不可能逐字节一致。
    # 实测根因（逐字段 diff：只有 children[i].child_dir 一项不同）。按既有先例处理：
    # 改为 namespace 相对路径并保留名字 + 脱敏标志 + 原因，而不是把 batch_manifest 丢进 allowlist。
    for c in children:
        c["child_dir_absolute_redacted"] = True
        c["child_dir"] = c.get("dir_name")
        c["path_redaction_reason"] = ("绝对路径含 namespace（每轮不同）；改为 namespace 相对路径，"
                                      "文件名仍保留以便审计")
    if extra:
        manifest.update(extra)
    w = atomic_write_json(rd / "batch_manifest.json", manifest)
    manifest["manifest_path"] = w.get("path")
    manifest["manifest_write_ok"] = bool(w.get("ok"))
    manifest["manifest_sha256"] = sha256_file(rd / "batch_manifest.json")
    return manifest


def run_supervisor(args) -> int:
    rd = RUNS / args.run_id
    rd.mkdir(parents=True, exist_ok=True)
    combos = [tuple(c) for c in args.combos][:min(args.max_combos, args.batch_size)]
    criteria = load_criteria_hashes()
    th = Thresholds()
    result: dict = {
        "run_id": args.run_id, "role": "supervisor", "at": now_iso(),
        "drive_mode": DRIVE_MODE, "freqs_MHz": list(args.freqs),
        "freqs_parse": getattr(args, "freqs_parse", None),
        "combos_requested": [list(c) for c in args.combos],
        "combos_delivered": [list(c) for c in combos],
        "server_lifecycle_size": SERVER_LIFECYCLE_SIZE,
        "batch_size": args.batch_size,
        "batch_size_allowed": list(ALLOWED_BATCH_SIZES),
        "batch_size_forbidden": list(FORBIDDEN_BATCH_SIZES),
        "criteria_hashes": criteria,
        "thresholds": th.to_dict(),
        "run_id_guard": getattr(args, "run_id_guard", None),
        "attended_operation": ATTENDED_OPERATION,
        "drill": bool(getattr(args, "drill", False)),
        "drill_thresholds": (resolve_thresholds(args)[1] if getattr(args, "drill", False) else None),
        "drill_note": DRILL_NOTE if getattr(args, "drill", False) else None,
        "preflight_gates": {"physical_avail_gate_mb": args.avail_gate,
                            "commit_gate_mb": args.commit_gate,
                            "note": "演练模式下前置门禁照常执行，不因演练而跳过"},
        "retry_policy": {"auto_retry_once_for_transient": bool(args.allow_retry),
                         "policy_ref": "Codex 2026-09-14 §6"},
        "model_sha256": sha256_file(MODEL), "script_sha256": sha256_file(SELF),
        "sampler_sha256": sha256_file(SIDECAR),
        "children": [], "blocked_reason": None, "retry_class": None, "retry_reason": None,
        "auto_retry_attempted": False, "simulated": False,
    }
    for idx, (x, n1) in enumerate(combos):
        pre = preflight(args.avail_gate, args.commit_gate)
        result.setdefault("preflights", []).append({"child_index": idx, **pre})
        if not pre["gate_pass"]:
            # 前置门禁失败与"child 失败"不同：没有分类器意见可给 ⇒ retry_* 保持 None
            _set_blocked(result, f"preflight_gate_failed(child_{idx:02d})")
            result["blocked_detail"] = pre
            break
        child = supervise_child(args.run_id, idx, x, n1, args, attempt=1)
        result["children"].append(child)
        if child["status"] != "pass":
            rc1 = child.get("retry_classification") or {}
            if rc1.get("retry") and args.allow_retry:
                result.setdefault("retries", []).append(
                    {"child_index": idx, "attempt": 1, "classification": rc1,
                     "preserved_attempt_1_dir": child.get("child_dir")})
                child2 = supervise_child(args.run_id, idx, x, n1, args, attempt=2)
                result["children"].append(child2)
                if child2["status"] != "pass":
                    rc2 = child2.get("retry_classification") or {}
                    same = rc2.get("class") == rc1.get("class")
                    _set_blocked(
                        result,
                        f"child_{idx:02d}_attempt_2_not_pass:status={child2['status']}"
                        + ("（attempt 2 重复同一瞬态错误，§6 禁止第三次重跑）" if same else ""),
                        retry_class=rc2.get("class"), retry_reason=rc2.get("reason"),
                        auto_retry_attempted=True)
                    break
            else:
                _set_blocked(
                    result, f"child_{idx:02d}_not_pass:status={child['status']}",
                    retry_class=rc1.get("class"), retry_reason=rc1.get("reason"),
                    auto_retry_attempted=False)
                break
        if child.get("blocks_next_combination"):
            # 软线告警阻塞下一组合：不是 child 失败 ⇒ 无重跑分类
            _set_blocked(result, "soft_line_blocks_next_combination")
            break

    # 批次级验收（含 commit 项）
    children = result["children"]
    result["aggregate_pass_conditions"] = {
        "children_delivered_ge_1": len(children) >= 1,
        "all_children_pass": bool(children) and all(c["status"] == "pass" for c in children),
        "all_have_checkpoint": all(c["checkpoint_present"] for c in children),
        "no_blocked_reason": result["blocked_reason"] is None,
        "commit_hard_stop_samples_0": all(
            (c.get("pass_conditions") or {}).get("commit_hard_stop_samples_0") is True
            for c in children),
        "min_commit_gt_hard_stop": all(
            (c.get("pass_conditions") or {}).get("min_commit_gt_hard_stop") is True
            for c in children),
        "lt2c_quick_gate_pass_all": all(
            (c.get("pass_conditions") or {}).get("lt2c_quick_gate_pass") is True
            for c in children),
        "no_cancel_triggered": all(
            (c.get("pass_conditions") or {}).get("no_cancel_triggered") is True
            for c in children),
        "child_evidence_isolated": all(
            (c.get("child_dir") and Path(c["child_dir"]).is_dir()) for c in children),
        "all_timelines_preserved": all(
            (c.get("attempt") != 1 or c.get("timeline_present")) for c in children),
        "termination_verified_when_enforced": all(
            (c.get("hard_stop_termination") is None)
            or (c["hard_stop_termination"].get("post_verification") or {}).get("verified") is True
            or c["hard_stop_termination"].get("refused") is not None
            for c in children),
    }
    result["status"] = ("PASS" if all(result["aggregate_pass_conditions"].values())
                        else "BLOCKED_OR_LIMITED")
    # 批次根目录**只**写聚合 manifest；child 证据全部留在各自目录
    result["child_dirs"] = [
        {"child_index": c.get("child_index"), "attempt": c.get("attempt"),
         "child_dir": c.get("child_dir"), "status": c.get("status"),
         "timeline_sha256": c.get("timeline_sha256"),
         "timeline_present": c.get("timeline_present"),
         "checkpoint_sha256": c.get("checkpoint_sha256"),
         "sampler_state_sha256": c.get("sampler_state_sha256"),
         "worker_state_sha256": c.get("worker_state_sha256")}
        for c in children]
    result["child_dir_inventory"] = [
        describe_child_dir(Path(c["child_dir"]))
        for c in children if c.get("child_dir") and Path(c["child_dir"]).is_dir()]
    result["child_dir_file_spec"] = CHILD_FILE_SPEC
    result["child_required_by_kind"] = CHILD_REQUIRED_BY_KIND
    # ---- ② 冻结证据：运行前（main 已核验，随 args 传入）+ 运行后各一次，两次一致才 true ----
    # 只读、无副作用；`--fixed-timestamps` 下时间戳走固定时钟，保证产物可复算。
    _fid = getattr(args, "freeze_id", None)
    _fclock = (FIXED_CLOCK_ISO if getattr(args, "fixed_timestamps", False) else None)
    _pre = getattr(args, "freeze_pre", None)
    _post = freeze_verify(_fid, fixed_at=_fclock) if _fid else None
    _ev = freeze_evidence(_fid, _pre, _post, script_sha256=result.get("script_sha256"))
    result["freeze_id"] = _fid
    result["freeze_evidence"] = _ev
    # 三个单义布尔（裁定 2）：顶层与 freeze_evidence 内**同一来源**，避免两处各算一遍而分叉
    result["freeze_hash_pre_post_match"] = _ev["freeze_hash_pre_post_match"]
    result["executed_from_frozen_snapshot"] = _ev["executed_from_frozen_snapshot"]
    result["freeze_evidence_complete"] = _ev["freeze_evidence_complete"]
    res = atomic_write_json(rd / "batch_manifest.json", result)
    if getattr(args, "drill", False):
        (rd / "DRILL_README.txt").write_text(
            "*** 本 run 是 DRILL（演练），不是生产运行 ***\n\n"
            f"run_id = {args.run_id}\n"
            f"drill_thresholds = {json.dumps(resolve_thresholds(args)[1], ensure_ascii=False)}\n\n"
            f"{DRILL_NOTE}\n\n"
            "用途：Codex §8 要求的真机硬停演练（U1 全路径 / U2 对真实 comsolmphserver 的终止 / "
            "U3 study 阻塞期间被终止后的行为）。\n"
            "请勿把本 run 的任何证据当作真实资源越线或用于资源放行判断。\n",
            encoding="utf-8")
    print("RESULT:", json.dumps({"run_id": args.run_id, "status": result["status"],
                                 "children": len(children),
                                 "blocked_reason": result["blocked_reason"],
                                 "aggregate_pass_conditions": result["aggregate_pass_conditions"],
                                 "manifest_write_ok": res.get("ok")}, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "PASS" else 6


# --------------------------------------------------------------------------- #
# dry-run：用模拟样本序列驱动**同一份**门禁与状态机（不启动 COMSOL）
# --------------------------------------------------------------------------- #
def _sim_samples_normal(n: int) -> list[dict]:
    out = []
    for i in range(n):
        frac = i / max(1, n - 1)
        out.append({"system_available_physical_mb": 16000 - 5000 * frac,
                    "system_memory_load_percent": int(48 + 30 * frac),
                    "commit_available_mb": 11000 - 4000 * frac,
                    "server_working_set_mb": 1200 + 9600 * frac,
                    "server_peak_working_set_mb": 1200 + 9600 * frac,
                    "current_stage": "solve"})
    return out


def _sim_samples_ws_hard(n: int) -> list[dict]:
    out = _sim_samples_normal(n)
    for s in out[-2:]:
        s["server_working_set_mb"] = 12300.0
        s["server_peak_working_set_mb"] = 12300.0
    return out


def _sim_samples_soft_only(n: int) -> list[dict]:
    out = _sim_samples_normal(n)
    for s in out:
        s["server_working_set_mb"] = 11600.0        # ≥11500 软线
        s["server_peak_working_set_mb"] = 11600.0
        s["commit_available_mb"] = 5000.0           # ≤6144 软线，>4096 不触硬线
    return out


def _sim_samples_r0_measured(limit: int = 40) -> list[dict]:
    """**真实实测样本回放**：读 R0 v2 的 resource_timeline.csv（只读，不跑 COMSOL）。"""
    csv_f = RUNS / "lt2-resource-calibration-x080-n02-v2" / "resource_timeline.csv"
    if not csv_f.is_file():
        return []
    out = []
    with csv_f.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            out.append({"system_available_physical_mb": r.get("system_available_physical_mb"),
                        "system_memory_load_percent": r.get("system_memory_load_percent"),
                        "commit_available_mb": r.get("commit_available_mb"),
                        "server_working_set_mb": r.get("server_working_set_mb"),
                        "server_peak_working_set_mb": r.get("server_peak_working_set_mb"),
                        "current_stage": r.get("current_stage")})
            if len(out) >= limit:
                break
    return out


def run_dry_run(args) -> int:
    """模拟样本驱动门禁 + 状态机；**不启动 server、不调用 mph**。"""
    rd = RUNS / args.run_id / "dryrun"
    rd.mkdir(parents=True, exist_ok=True)
    th = Thresholds()
    scenarios = [
        {"name": "normal_headroom", "samples": _sim_samples_normal(8),
         "expect": {"cancel": False, "deliver_next": True}},
        {"name": "ws_hard_stop", "samples": _sim_samples_ws_hard(8),
         "expect": {"cancel": True, "deliver_next": False}},
        {"name": "soft_only", "samples": _sim_samples_soft_only(8),
         "expect": {"cancel": False, "deliver_next": False}},
        {"name": "r0_v2_measured_replay", "samples": _sim_samples_r0_measured(40),
         "expect": {"cancel": None, "deliver_next": None}},
    ]
    out: dict = {"run_id": args.run_id, "role": "dry-run", "at": now_iso(),
                 "simulated": True,
                 "data_provenance": "SIMULATED / 实测回放 —— 非本次 COMSOL 求解结果，禁止用于任何分析",
                 "run_id_guard": getattr(args, "run_id_guard", None),
                 "thresholds": th.to_dict(), "scenarios": [],
                 "server_started": False, "mph_imported": False}
    (rd / "README.txt").write_text(
        "本目录全部为 dry-run 模拟产物（无 COMSOL 求解）。禁止当作仿真证据使用。\n",
        encoding="utf-8")

    for sc in scenarios:
        engine = GateEngine(th=th)
        if not sc["samples"]:
            out["scenarios"].append({"name": sc["name"], "skipped": "无样本（来源文件缺失）"})
            continue
        verdicts, actions, first_cancel = [], [], None
        t = time.time()
        for i, s in enumerate(sc["samples"]):
            sample = dict(s)
            sample.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S"))
            sample["simulated"] = True
            v = engine.evaluate(sample, now=t + i * th.sample_interval_s)
            health = sidecar_health(t + i * th.sample_interval_s,
                                    engine.last_sample_ts, True)
            a = decide_next_action(v, health, {"cancel_requested": False})
            verdicts.append(v["verdict"])
            actions.append(a["action"])
            if a["action"] == "hard_stop_enforce" and first_cancel is None:
                first_cancel = {"sample_index": i + 1, "reason": a["reason"],
                                "source": a["source"]}
        after = decide_after_combo(engine, True)
        # 干跑也要走 checkpoint 原子写路径
        ck = atomic_write_json(rd / f"dryrun_{sc['name']}_checkpoint.json",
                               {"scenario": sc["name"], "simulated": True,
                                "verdicts": verdicts, "engine": engine.to_dict(),
                                "pass_conditions_example": combo_pass_conditions(
                                    [], {"timeline_gaps_over_15s": [],
                                         "solve_stage_missing_system_columns": [],
                                         "commit_hard_stop_samples": sum(
                                             1 for x in sc["samples"]
                                             if float(x.get("commit_available_mb") or 1e9)
                                             <= th.commit_hard_stop_mb),
                                         "server_peak_ws_mb": max(
                                             float(x.get("server_peak_working_set_mb") or 0)
                                             for x in sc["samples"]),
                                         "system_available_physical_mb": {"min": min(
                                             float(x.get("system_available_physical_mb") or 0)
                                             for x in sc["samples"])},
                                         "commit_available_mb": {"min": min(
                                             float(x.get("commit_available_mb") or 1e9)
                                             for x in sc["samples"])}},
                                    {"checks": {"pass": True}}, None, th)})
        exp = sc["expect"]
        ok_cancel = (exp["cancel"] is None) or (bool(first_cancel) == exp["cancel"])
        ok_next = (exp["deliver_next"] is None) or (
            after["deliver_next"] == exp["deliver_next"])
        out["scenarios"].append({
            "name": sc["name"], "n_samples": len(sc["samples"]),
            "verdict_counts": {k: verdicts.count(k) for k in ("ok", "warning", "hard_stop")},
            "first_cancel": first_cancel,
            "after_combo": after,
            "checkpoint_write_ok": ck.get("ok"),
            "checkpoint_path": ck.get("path"),
            "expect": exp, "cancel_as_expected": ok_cancel, "next_as_expected": ok_next,
            "passed": bool(ok_cancel and ok_next and ck.get("ok")),
        })

    out["all_scenarios_passed"] = all(s.get("passed") for s in out["scenarios"]
                                      if "skipped" not in s)
    atomic_write_json(rd / "dry_run_report.json", out)
    print("DRY-RUN:", json.dumps(
        {"all_scenarios_passed": out["all_scenarios_passed"],
         "scenarios": [{"name": s["name"], "verdicts": s.get("verdict_counts"),
                        "first_cancel": (s.get("first_cancel") or {}).get("source"),
                        "deliver_next": (s.get("after_combo") or {}).get("deliver_next"),
                        "passed": s.get("passed")} for s in out["scenarios"]]},
        ensure_ascii=False), flush=True)
    return 0 if out["all_scenarios_passed"] else 7


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def resolve_combos(s: str | None) -> list[tuple[float, int]]:
    if not s:
        return list(DEFAULT_COMBOS)
    raw = json.loads(s)
    out = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((float(item[0]), int(item[1])))
        else:
            raise ValueError(f"--combos 元素必须是 [x_scale, N_w_te1]：{item!r}")
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="LT2 生产 runner（supervisor / combo-worker / dry-run / preflight）")
    ap.add_argument("--run-id", default=None,
                    help="必填；--dry-run 省略时自动生成带时间戳的唯一值")
    ap.add_argument("--force-reuse-run-id", action="store_true",
                    help="允许写入已存在且非空的 work\\runs\\<run-id>\\（默认拒绝，防覆盖 append-only 产物）")
    ap.add_argument("--role", choices=["supervisor", "combo-worker", "fake-combo-worker"],
                    default="supervisor")
    ap.add_argument("--combos", default=None, help="JSON，例如 '[[0.6,4],[0.7,5]]'")
    ap.add_argument("--freqs", default=",".join(DEFAULT_FREQS))
    ap.add_argument("--expect-freq-count", type=int, default=None,
                    help=f"期望频率条数（fail-closed 校验）；默认 {EXPECTED_FREQ_COUNT}"
                         f"（= 生产授权口径 len(DEFAULT_FREQS)）；非生产点数必须显式覆盖")
    ap.add_argument("--freeze-id", default=None,
                    help="冻结 id（形如 freeze-YYYYmmdd-HHMM）：批次前后各做一次只读冻结核验，"
                         "两次结果与时间戳写入 batch_manifest.json（②）；"
                         "给了但核验无法完成/不通过 ⇒ 拒绝启动（exit 11）")
    ap.add_argument("--max-combos", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=4,
                    help="逻辑批大小：4/6/8（12–16 被授权明令禁止）")
    ap.add_argument("--avail-gate", type=float, default=PREFLIGHT_AVAIL_MB,
                    help=f"前置可用物理内存门禁 MB（Codex 值 {PREFLIGHT_AVAIL_MB:g}）")
    ap.add_argument("--commit-gate", type=float, default=PREFLIGHT_COMMIT_MB,
                    help=f"前置 commit 可用门禁 MB（Codex 值 {PREFLIGHT_COMMIT_MB:g}）")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--gate-poll", type=float, default=GATE_POLL_S)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--assemble-manifest-only", action="store_true",
                    help="只读扫描 <run-id>/child_*_attempt_* 并写批次根 batch_manifest.json"
                         "（不启动 server / 不 import mph）")
    ap.add_argument("--fixed-timestamps", action="store_true",
                    help="确定性时钟：固定日志/manifest 的时间戳 ⇒ 产物可复算"
                         "（**仅供自测与证据复算**）")
    ap.add_argument("--no-retry", dest="allow_retry", action="store_false", default=True,
                    help="关闭 §6 的「瞬态失败自动重跑一次」（默认开启）")
    ap.add_argument("--drill", action="store_true",
                    help="演练模式（仅用于 U1/U2/U3 真机验证）：配合下面的阈值覆盖，"
                         "用**故意压低**的阈值在 solve 阻塞期间触发硬停；"
                         "所有产物带 drill 标识，绝不可用于生产")
    ap.add_argument("--ws-hard-stop-mb", type=float, default=None)
    ap.add_argument("--commit-hard-stop-mb", type=float, default=None)
    ap.add_argument("--physical-hard-stop-mb", type=float, default=None)
    ap.add_argument("--worker-role", default="combo-worker",
                    choices=["combo-worker", "fake-combo-worker"],
                    help="supervisor 拉起哪个 worker 角色（fake 仅用于无 COMSOL 的接线冒烟测试）")
    # combo-worker 专用
    ap.add_argument("--combo", default=None, help="[x_scale, N_w_te1]（worker 用）")
    ap.add_argument("--child-index", type=int, default=0)
    ap.add_argument("--attempt", type=int, default=1,
                    help="child attempt 序号（1 = 首次，2 = §6 允许的唯一一次自动重跑）")
    args = ap.parse_args(argv)

    if args.batch_size in FORBIDDEN_BATCH_SIZES:
        print(f"[STOP] 批大小 {args.batch_size} 被授权明令禁止（禁止 12–16）", flush=True)
        return 3
    if args.batch_size not in ALLOWED_BATCH_SIZES:
        print(f"[STOP] 批大小 {args.batch_size} 不在授权集合 {ALLOWED_BATCH_SIZES}", flush=True)
        return 3

    # 阈值覆盖只在 --drill 下允许；否则**直接拒绝**（防止误把演练阈值用于生产）
    _over = [k for k in DRILL_THRESHOLD_ARGS if getattr(args, k, None) is not None]
    if _over and not args.drill:
        print(f"[STOP] 阈值覆盖 {_over} 只在 --drill 演练模式下允许；"
              f"生产运行必须使用 Codex 裁定阈值（防止误用）", flush=True)
        return 9
    if args.drill:
        th_drill, drill_rec = resolve_thresholds(args)
        print(f"[DRILL] 演练模式已启用；阈值覆盖 = "
              f"{json.dumps(drill_rec['overrides'], ensure_ascii=False)}；"
              f"{DRILL_NOTE}", flush=True)
    # ---- ③ `--freqs` 解析：fail-closed，防「不报错但事实已变」----
    args.freqs, args.freqs_parse = parse_freqs(args.freqs, args.expect_freq_count)
    print("[INFO] --freqs 解析：" + json.dumps({
        "raw": args.freqs_parse["raw"],
        "parsed_freq_list_MHz": args.freqs_parse["parsed_freq_list_MHz"],
        "count": args.freqs_parse["parsed_freq_list_MHz_count"],
        "expected_count": args.freqs_parse["expected_count"],
        "expected_count_source": args.freqs_parse["expected_count_source"],
        "canonical_plist": args.freqs_parse["canonical_plist"]}, ensure_ascii=False), flush=True)
    if not args.freqs_parse["ok"]:
        print("[STOP] --freqs 解析拒绝启动（fail-closed，防静默变形）："
              + json.dumps(args.freqs_parse["problems"], ensure_ascii=False), flush=True)
        print("       parse_record = " + json.dumps(args.freqs_parse, ensure_ascii=False),
              flush=True)
        return FREQ_PARSE_REFUSAL_EXIT

    # ---- ② 冻结核验（运行前）：只读；不通过就**不启动**（避免白跑一整批才发现无法出证据）----
    # `--assemble-manifest-only` 是只读重建（不是一次运行，也不写 ②字段），故不做核验。
    args.freeze_pre = None
    if getattr(args, "freeze_id", None) and args.role == "supervisor" \
            and not args.assemble_manifest_only:
        args.freeze_pre = freeze_verify(
            args.freeze_id, fixed_at=(FIXED_CLOCK_ISO if args.fixed_timestamps else None))
        print("[INFO] 冻结核验（运行前）: " + json.dumps({
            "freeze_id": args.freeze_id,
            "verdict": args.freeze_pre.get("verdict"),
            "drift_count": args.freeze_pre.get("drift_count"),
            "frozen_file_count": args.freeze_pre.get("frozen_file_count"),
            "manifest_path": args.freeze_pre.get("manifest_path")}, ensure_ascii=False), flush=True)
        if not args.freeze_pre.get("ok"):
            print(f"[STOP] 冻结核验未通过（{args.freeze_pre.get('verdict')}），拒绝启动："
                  f"{args.freeze_pre.get('problem')}", flush=True)
            for d in (args.freeze_pre.get("drift") or [])[:20]:
                print("       drift: " + json.dumps(d, ensure_ascii=False), flush=True)
            return FREEZE_UNRESOLVED_EXIT

    # --run-id：dry-run 自动给唯一值（带时间戳 + pid），避免两次干跑互相踩
    if not args.run_id:
        if args.dry_run:
            args.run_id = f"lt2-dryrun-{time.strftime('%Y%m%d-%H%M%S')}-pid{os.getpid()}"
            print(f"[INFO] --dry-run 未给 --run-id，自动生成唯一值：{args.run_id}", flush=True)
        else:
            print("[STOP] 非 --dry-run 必须显式给 --run-id", flush=True)
            return 3

    # 只读组装 manifest：需要读既有非空 run 目录，故**跳过**复用防护（本身不产生 child 证据）
    if args.assemble_manifest_only:
        m = assemble_manifest_from_child_dirs(
            args.run_id, fixed_at=(FIXED_CLOCK_ISO if args.fixed_timestamps else None))
        print("MANIFEST:", json.dumps({
            "run_id": args.run_id, "child_count": m["child_count"],
            "children_satisfy_inventory": m["children_satisfy_inventory"],
            "manifest_path": m["manifest_path"], "manifest_write_ok": m["manifest_write_ok"],
            "manifest_sha256": m["manifest_sha256"],
            "kinds": {c["dir_name"]: c["kind"] for c in m["children"]},
        }, ensure_ascii=False), flush=True)
        return 0 if m["manifest_write_ok"] else 8

    # run-id 复用防护：**只对 supervisor 生效**。
    # worker 角色（combo-worker / fake-combo-worker）由 supervisor 拉起，run 目录已被 supervisor
    # 建立并通过守卫，worker 必须跳过——否则会把自己拦下（实测：fake-combo-worker 曾因此 exit 4）。
    guard = {"ok": True, "action": "skipped_non_supervisor_role", "role": args.role}
    if args.role == "supervisor":
        guard = run_id_reuse_guard(args.run_id, args.force_reuse_run_id)
        if not guard.get("ok"):
            if guard.get("action") == "refused_invalid_run_id":
                print(f"[STOP] run-id 不合法：{args.run_id} → {guard.get('reasons')}", flush=True)
            else:
                print(f"[STOP] run 目录已存在且非空，拒绝启动（保护 append-only 产物）："
                      f"{guard.get('run_dir')}", flush=True)
                print(f"       现有条目 {guard.get('existing_entries')} 个，例如 {guard.get('sample')}", flush=True)
                print(f"       {guard.get('hint')}", flush=True)
            return 4
        if guard.get("forced"):
            print(f"[WARN] 已按 --force-reuse-run-id 复用非空 run 目录：{guard.get('run_dir')} "
                  f"（{guard.get('existing_entries')} 个既有条目）", flush=True)
    args.run_id_guard = guard

    if args.role == "combo-worker":
        if not args.combo:
            print("[STOP] combo-worker 必须给 --combo", flush=True)
            return 3
        args.combo = tuple(json.loads(args.combo))
        return run_combo_worker(args)

    if args.role == "fake-combo-worker":
        if not args.combo:
            print("[STOP] fake-combo-worker 必须给 --combo", flush=True)
            return 3
        args.combo = tuple(json.loads(args.combo))
        return run_fake_combo_worker(args)

    if args.preflight_only:
        pre = preflight(args.avail_gate, args.commit_gate)
        rd = RUNS / args.run_id
        rd.mkdir(parents=True, exist_ok=True)
        r = atomic_write_json(rd / "preflight_only.json", pre)
        print("PREFLIGHT:", json.dumps(pre, ensure_ascii=False), "| write_ok =", r.get("ok"),
              flush=True)
        return 0 if pre["gate_pass"] else 5

    if args.dry_run:
        return run_dry_run(args)

    args.combos = resolve_combos(args.combos)
    return run_supervisor(args)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
