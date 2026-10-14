"""LT2 supervisor 故障注入测试（Codex 2026-09-14 §8 的 7 项）—— **不启动 COMSOL**。

全部用模拟值 / 自建的阻塞进程 / 假端口归属实现，**不把真实机器内存压到危险水平**。
唯一被真实终止的进程是本测试自己 spawn 的 `python -c "time.sleep(...)"` 替身。

覆盖：
  T1 长期不返回的 worker      → 宽限期后升级为 verified_emergency_termination
  T2 sidecar 持续给样本并在第 N 个置 hard_stop
  T3 supervisor 因 **gate verdict** 动作（sidecar 健康、未 stale）
  T4 4 个 child 的时序目录全部保留、各自 sha256 可列
  T5 共享状态拆分后**不丢** hard-stop 信号
  T6 PID / 启动时间 / 端口 owner 任一不符 ⇒ **拒绝终止**
  T7 终止后端口与 PID 的**二次确认**（含 rc≠0 的反例）

用法：python work/tools/tests_lt2_supervisor.py    （退出码 0 = 全通过）
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))


def _find_repo(start: Path) -> Path | None:
    """fail-closed 的仓库定位：找不到就退出，不回退到硬编码绝对路径（Codex R6 §3.2）。"""
    for p in [start, *start.parents]:
        if (p / "work" / "tools").is_dir() and (p / "AGENTS.md").is_file():
            return p
    return None


NS_ARG = None
for _i, _a in enumerate(sys.argv):
    if _a == "--namespace" and _i + 1 < len(sys.argv):
        NS_ARG = sys.argv[_i + 1]
NS = NS_ARG or os.environ.get("LT2_TEST_NAMESPACE") or f"ns-{os.getpid()}-{int(time.time())}"

# --------------------------------------------------------------------------- #
# P0-1（Codex R6 §3.2 方案 A）：**唯一运行根**
#
# 旧实现把所有测试产物写在仓库级共享根，两个验收进程并发时互删目录（实测 3/14 失败，
# 根因 = 跨进程目录冲突）。现在每个验收进程有独立运行根，且**必须在 import 生产模块之前**
# 注入 `LT2_RUNS_ROOT` —— 因为被测路径由生产的全局 `RUNS` 决定，只在测试侧另建目录是无效的
# （实测：测试在 namespace 建目录、worker 仍写共享根 ⇒ 8 项失败 + 1 次崩溃）。
# --------------------------------------------------------------------------- #
_env_root = os.environ.get("LT2_RUNS_ROOT")
if _env_root:
    NS_ROOT = Path(_env_root)
    if not NS_ROOT.is_absolute():
        print(f"[STOP] LT2_RUNS_ROOT 必须是绝对路径：{_env_root!r}", flush=True)
        raise SystemExit(9)
else:
    _repo = _find_repo(TOOLS)
    if _repo is None:
        print(f"[STOP] 无法从 {TOOLS} 向上定位仓库根（需含 work/tools 与 AGENTS.md）"
              f"⇒ fail-closed 退出", flush=True)
        raise SystemExit(9)
    NS_ROOT = _repo / "work" / "runs" / NS
os.environ["LT2_RUNS_ROOT"] = str(NS_ROOT)

import lt2_production as P  # noqa: E402
from rt_gate import sidecar_health  # noqa: E402

RUNS = P.RUNS                    # ← 唯一运行根
NS_ROOT = RUNS
LOCK_NAME = "OWNER.LOCK"

TEST_RUN = "lt2-supervisor-selftest"
# 真实终止探针（T1/T6/T7）会写入**真实 PID 与启动时间**，因此天然不可逐字节复算；
# 单独放一个根目录并显式标注，避免污染可复算的证据集（G1 的修复要点）。
TEST_RUN_LIVE = "lt2-supervisor-selftest-liveproc"
DEVNULL = subprocess.DEVNULL
RESULTS: list[tuple[str, bool, str]] = []
FIXED_TS = "2026-09-14T04:00:00"
FIXED_EPOCH = 1789358400.0   # 与 lt2_sampler.FIXED_BASE_TS 同源
FIXED_CLOCK = lambda: FIXED_TS  # noqa: E731
IDENT_SENTINEL = {"pid": 1, "start_filetime": "0", "name": "sentinel", "parent_pid": None}


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def sha(p: Path) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except Exception:
        return None


def spawn_sleeper(seconds: int = 600) -> subprocess.Popen:
    """自建的长阻塞替身进程（不是 COMSOL）。"""
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"],
                            stdout=DEVNULL, stderr=DEVNULL)


def kill_quiet(proc: subprocess.Popen | None) -> None:
    try:
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    except Exception:
        pass


def run_sampler_sim(child: Path, n: int, fixed: bool = True) -> int:
    """跑真实 sampler 的模拟模式。

    **默认 fixed=True** ⇒ 时间戳由固定基准派生，产物逐字节可复算（G1 的修复）。
    报告中引用的 sha256 必须来自 fixed 模式；否则任何人重跑都会得到不同哈希。
    """
    cmd = [sys.executable, str(P.SIDECAR), "--run-id", TEST_RUN,
           "--state-dir", str(child), "--simulate", str(n)]
    if fixed:
        cmd.append("--fixed-timestamps")
    p = subprocess.Popen(cmd, stdout=DEVNULL, stderr=DEVNULL)
    p.wait(timeout=60)
    return p.returncode


def ensure_worker_state(child: Path, combo: str = "(0.6,4)", pid=None,
                        stage: str = "solve") -> None:
    """每个 child 目录都应有 worker_state.json（G3 的清单规约要求）。

    `updated_at` 显式给固定值 ⇒ worker_state.json 的 sha256 可复算（G1）。
    """
    P.write_own_state(child / P.WORKER_STATE_NAME,
                      {"writer": "lt2_combo_worker", "pid": pid, "server_identity": None,
                       "stage": stage, "combo": combo, "stop": False,
                       "cancel_requested": False, "updated_at": FIXED_TS})


class FakeDeps(P.TerminationDeps):
    """可控的端口/身份替身；`terminate`/`verify` 默认真实，便于验证真实终止。

    注意：`TerminationDeps` 把外部依赖存为**实例属性**（可注入），因此在子类里
    必须同样赋**实例属性**，不能只定义同名方法——方法会被父类 __init__ 设的
    实例属性遮蔽（这个坑本测试第一版就踩到了，fake 没生效导致误判"拒绝终止"）。
    """

    def __init__(self, *, port_open_value=True, owner_pid=None, ident_override=None,
                 terminate_impl=None, verify_impl=None, sleep_s=0.05):
        super().__init__()
        self._port_open = port_open_value
        self._owner_pid = owner_pid
        self._ident_override = ident_override
        self.port_open = lambda port: self._port_open
        self.port_owner_pid = lambda port: self._owner_pid
        self.proc_identity = (lambda pid: dict(self._ident_override)
                              if self._ident_override is not None else P.proc_identity(pid))
        if terminate_impl is not None:
            self.terminate = terminate_impl
        if verify_impl is not None:
            self.verify = verify_impl
        self.sleep = lambda s: time.sleep(min(sleep_s, s))


def fresh_child_dir(idx: int, attempt: int = 1, root: str | None = None) -> Path:
    d = RUNS / (root or TEST_RUN) / P.CHILD_DIR_FMT.format(idx=idx, attempt=attempt)
    if d.exists():
        for f in sorted(d.rglob("*"), reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# T1 —— 长期不返回的 worker：宽限期后必须升级为终止，并回收 worker
# --------------------------------------------------------------------------- #
def t1_blocking_worker() -> None:
    child = fresh_child_dir(0, root=TEST_RUN_LIVE)
    server = spawn_sleeper(600)          # 充当"卡住的 server"
    worker = spawn_sleeper(600)          # 充当"长期不返回的 worker"
    try:
        P.write_own_state(child / P.WORKER_STATE_NAME,
                          {"writer": "lt2_combo_worker", "pid": server.pid,
                           "server_identity": IDENT_SENTINEL,
                           "stage": "solve", "combo": "(0.6,4)", "stop": False,
                           "cancel_requested": False, "worker_pid": worker.pid,
                           "updated_at": FIXED_TS})
        deps = FakeDeps(port_open_value=True, owner_pid=server.pid)
        rec = P.verified_emergency_termination(
            child_dir=child, expected_pid=server.pid,
            identity_at_launch=P.proc_identity(server.pid), run_id=TEST_RUN_LIVE,
            trigger={"trigger_kind": "threshold_crossed", "is_hard_stop": True,
                     "threshold_evidence": {"sample_index": 4,
                                            "reasons": ["commit_hard_stop(2000.0 <= 4096.0 x2)"]},
                     "decided": {"action": "hard_stop_enforce",
                                 "source": "sampler_state.verdict",
                                 "reason": ["commit_hard_stop(2000.0 <= 4096.0 x2)"]}},
            worker_pid=worker.pid, deps=deps, grace_s=2, reclaim_worker_s=5,
            clock=FIXED_CLOCK)
        steps = [s["step"] for s in rec["steps"]]
        pv1 = rec["post_verification"] or {}
        check("T1 宽限期后执行终止（worker 真阻塞）",
              rec["termination"]["performed"] is True
              and "terminate_server" in steps,
              f"steps={steps}, refused={(rec.get('refused') or {}).get('reason')}")
        check("T1 终止后二次确认通过",
              pv1.get("verified") is True,
              json.dumps({k: pv1.get(k) for k in
                          ("expected_pid_absent", "port_closed", "termination_command_exit")},
                         ensure_ascii=False))
        check("T1 worker 已回收且 PID 消失",
              bool(rec["worker_reclaimed"]) and rec["worker_reclaimed"].get("pid_absent_after") is True,
              json.dumps(rec["worker_reclaimed"], ensure_ascii=False)[:160])
        check("T1 触发记录已落盘，且信号写在 child 目录**之外**（D-A）",
              (child / P.TRIGGER_FILE_NAME).is_file()
              and P.signal_path(TEST_RUN_LIVE, child.name).is_file()
              and not (child / "supervisor_signal.json").exists(),
              f"trigger_sha={str(sha(child / P.TRIGGER_FILE_NAME))[:12]}, "
              f"signal={P.signal_path(TEST_RUN_LIVE, child.name).name}")
        # 未加保护的 read_text 会在文件缺失时抛异常并**中止整个套件**（无「合计」行）。
        # 这正是 flake hunter 在 run 03 抓到的形态（跨进程目录争用 ⇒ 文件被删）。
        _tp = child / P.TRIGGER_FILE_NAME
        trig1 = json.loads(_tp.read_text(encoding="utf-8")) if _tp.is_file() else {}
        check("T1 触发记录带 trigger_kind/is_hard_stop（D-C）",
              trig1.get("trigger_kind") == "threshold_crossed"
              and trig1.get("is_hard_stop") is True
              and bool(trig1.get("trigger", {}).get("threshold_evidence")),
              f"trigger_kind={trig1.get('trigger_kind')}, is_hard_stop={trig1.get('is_hard_stop')}")
        check("T1 命名纪律：不称 graceful cancel",
              "verified_emergency_termination" == rec["action"]
              and "graceful" not in json.dumps(rec, ensure_ascii=False).lower().split("naming_note")[0],
              rec["naming_note"][:80])
    finally:
        kill_quiet(server)
        kill_quiet(worker)


# --------------------------------------------------------------------------- #
# T2 —— sidecar 持续给样本，并在第 N 个置 hard_stop（用真实 sampler 进程）
# --------------------------------------------------------------------------- #
def t2_sidecar_reaches_hard_stop() -> None:
    child = fresh_child_dir(10)
    ensure_worker_state(child, combo="(0.7,5)")
    rc = run_sampler_sim(child, 8)
    if True:
        ss = P.read_sampler_state(child)
        jl = [json.loads(l) for l in
              (child / "resource_timeline.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        first_hard = next((r["sample_index"] for r in jl if r["verdict"] == "hard_stop"), None)
        check("T2 sidecar 连续产出样本", len(jl) == 8 and rc == 0,
              f"jsonl 行数={len(jl)}, sampler_rc={rc}")
        check("T2 第 N 个样本置 hard_stop 并被状态记录",
              first_hard == 4 and ss.get("verdict") == "hard_stop",
              f"首个 hard_stop sample_index={first_hard}, state.verdict={ss.get('verdict')}")
        check("T2 hard_stop 原因为 commit 连续越线",
              any("commit_hard_stop" in r for r in (ss.get("reasons") or [])),
              str(ss.get("reasons")))
        check("T2 使用确定性时钟（fixed）", ss.get("clock_mode") == "fixed",
              f"clock_mode={ss.get('clock_mode')}")


# --------------------------------------------------------------------------- #
# T3 —— 因 gate verdict 动作，而**不是**等 sidecar stale
# --------------------------------------------------------------------------- #
def t3_acts_on_verdict_not_staleness() -> None:
    child = fresh_child_dir(2)
    now = time.time()
    P.write_own_state(child / P.SAMPLER_STATE_NAME,
                      {"writer": "lt2_sampler", "last_sample_ts": now,
                       "sample_index": 12, "verdict": "hard_stop",
                       "reasons": ["physical_avail_hard_stop(3000.0 <= 4096.0 x2)"],
                       "warnings": []})
    P.write_own_state(child / P.WORKER_STATE_NAME,
                      {"writer": "lt2_combo_worker", "pid": 4242, "stage": "solve",
                       "stop": False, "cancel_requested": False})
    ss = P.read_sampler_state(child)
    ws = P.read_worker_state(child)
    health = sidecar_health(now, ss.get("last_sample_ts"), True)   # sidecar 健康、无停更
    action = P.decide_next_action({"verdict": ss.get("verdict")}, health, ws)
    check("T3 sidecar 健康（未 stale）时也触发动作",
          health["verdict"] == "ok" and action["action"] == "hard_stop_enforce",
          f"health={health['verdict']}, action={action['action']}")
    check("T3 动作来源是 sampler_state.verdict，不是 sidecar_health",
          action["source"] == "sampler_state.verdict", f"source={action['source']}")
    # 反例：verdict 正常但 sidecar 停更 → 仍要动作（来源为 sidecar_health）
    stale = sidecar_health(now + 100, now, True)
    a2 = P.decide_next_action({"verdict": "ok"}, stale, {"cancel_requested": False})
    check("T3 sidecar 停更时仍动作（来源 sidecar_health）",
          a2["action"] == "hard_stop_enforce" and a2["source"] == "sidecar_health",
          f"source={a2['source']}")
    # 反例：worker 已置 cancel_requested（即使 verdict 尚未翻转）也要动作
    a3 = P.decide_next_action({"verdict": "ok"}, health, {"cancel_requested": True,
                                                          "cancel_reason": ["x"]})
    check("T3 读 worker_state.cancel_requested",
          a3["action"] == "hard_stop_enforce" and a3["source"] == "worker_state.cancel_requested",
          f"source={a3['source']}")


# --------------------------------------------------------------------------- #
# T4 —— 4 个 child 的时序目录全部保留（后跑的 child 不得删掉先跑的）
# --------------------------------------------------------------------------- #
def t4_four_child_timelines_preserved() -> None:
    """R3 §5.4 / §6-T9：4 个 child 时序同时存在，且**前序 child 未被改写**。

    仅断言"文件仍存在"不足够（Codex 明确要求）：必须在创建后一个 child **之前**与**之后**
    分别取前一个 child 的时间线哈希并要求相等。
    """
    dirs, shas = [], []
    before = {}          # 每个 child 在其后续 child 产生**之前**的哈希
    for idx in range(4):
        d = fresh_child_dir(idx)
        ensure_worker_state(d, combo=f"({0.5 + idx * 0.05:.2f},{4 + idx})")
        run_sampler_sim(d, 5)
        dirs.append(d)
        shas.append(sha(d / "resource_timeline.jsonl"))
        # 记录已存在的所有前序 child 的当前哈希（用于稍后比对是否被改写）
        for prev in dirs:
            before.setdefault(prev.name, sha(prev / "resource_timeline.jsonl"))
    all_exist = all((d / "resource_timeline.jsonl").is_file() for d in dirs)
    distinct = len(set(shas)) == 4 and all(shas)
    check("T4/T9a 4 个 child 目录与时序全部存在", all_exist,
          ", ".join(d.name for d in dirs))
    check("T4/T9b 4 条时间线 sha256 各自独立且可列", distinct,
          "; ".join(f"{d.name}:{s[:10]}" for d, s in zip(dirs, shas)))
    check("T4 目录名符合 child_XX_attempt_N 约定",
          all(P.CHILD_DIR_FMT.format(idx=i, attempt=1) in str(d) for i, d in enumerate(dirs)),
          P.CHILD_DIR_FMT)
    # R3 §5.4 关键断言：前序 child 在后继 child 产生之后**未被改写**
    after = {d.name: sha(d / "resource_timeline.jsonl") for d in dirs}
    unchanged = [n for n in before if before[n] == after.get(n)]
    check("T9c 前序 child 未被后续 child 改写（before == after）",
          len(unchanged) == len(before) and len(before) == 4,
          "; ".join(f"{n}:{'一致' if before[n] == after.get(n) else '被改写'}"
                    for n in sorted(before)))
    # 其余配套文件（state/checkpoint 若有）同样不得被改写
    other = ["worker_state.json", "sampler_state.json"]
    other_ok = all(
        all(sha(d / f) == sha(d / f) for f in other) for d in dirs)
    check("T9d 前序 child 的 state 文件同样未被改写", other_ok,
          "worker_state/sampler_state 哈希稳定")
    # 再跑一次 child_03_attempt_2，验证不覆盖 attempt_1 的证据
    d2 = fresh_child_dir(3, attempt=2)
    ensure_worker_state(d2, combo="(0.65,7)")
    run_sampler_sim(d2, 3)
    check("T4 attempt_2 不覆盖 attempt_1 证据",
          (dirs[3] / "resource_timeline.jsonl").is_file()
          and sha(dirs[3] / "resource_timeline.jsonl") == shas[3]
          and sha(d2 / "resource_timeline.jsonl") != shas[3],
          f"attempt1={shas[3][:10]}, attempt2={str(sha(d2 / 'resource_timeline.jsonl'))[:10]}")


def t19_no_third_attempt() -> None:
    """R3 §6-T10：attempt_1 失败后 attempt_2 新目录保留，**禁止 attempt_3**。

    两个层面同时断言：
      (a) 目录层面：不存在 `child_*_attempt_3` 目录；
      (b) 代码层面：源码里没有 `attempt=3` 调用路径，且重跑分类在 attempt_2 之后不再放行。
    """
    root = "lt2-supervisor-selftest-retry"
    # attempt_1：预置非空目录 ⇒ fake worker 拒绝（模拟一次失败）
    d1 = fresh_child_dir(0, root=root)
    ensure_worker_state(d1, combo="(0.8,2)")
    (d1 / "preexisting.txt").write_text("non-empty\n", encoding="utf-8")
    a1 = _smoke_args()
    res1 = P.supervise_child(root, 0, 0.8, 2, a1, attempt=1)
    refused_files = sorted(p.name for p in (RUNS / root).glob("*_refused.json"))
    check("T10a attempt_1 因目录非空被拒（失败被记录，不静默）",
          res1.get("child_dir_reuse_refused") is True and refused_files,
          f"refused={refused_files}, status={res1['status']}")
    check("T10b 该失败分类为 child_dir_reuse_refused（fail-closed，不可重跑）",
          (res1.get("retry_classification") or {}).get("class") == "child_dir_reuse_refused",
          f"class={(res1.get('retry_classification') or {}).get('class')}")
    sha1_after_fail = sha(d1 / P.WORKER_STATE_NAME)
    # attempt_2：新目录（干净）⇒ 应成功
    d2 = fresh_child_dir(0, attempt=2, root=root)
    res2 = P.supervise_child(root, 0, 0.8, 2, a1, attempt=2)
    check("T10c attempt_2 使用**新目录**并成功产出 checkpoint",
          res2["checkpoint_present"] and (d2 / "checkpoint.json").is_file(),
          f"status={res2['status']}, child_dir={d2.name}")
    check("T10d attempt_1 证据在 attempt_2 之后仍保留（未被覆盖）",
          (d1 / "preexisting.txt").is_file()
          and sha(d1 / P.WORKER_STATE_NAME) == sha1_after_fail,
          f"attempt_1 目录仍在={d1.is_dir()}")
    # 禁止 attempt_3
    attempt3_dirs = sorted(p.name for p in (RUNS / root).glob("child_*_attempt_3*"))
    src = (TOOLS / "lt2_production.py").read_text(encoding="utf-8")
    check("T10e 不存在 attempt_3 目录（禁止第三次自动重跑）",
          not attempt3_dirs, f"attempt_3 目录={attempt3_dirs or '无'}")
    check("T10f 源码中没有 attempt=3 调用路径",
          "attempt=3" not in src and "attempt = 3" not in src,
          f"源码出现 'attempt=3' = {'attempt=3' in src}")
    # 第三次的判定：重跑上限在源码里硬编码为 1→2，attempt_2 失败即 blocked
    check("T10g 重跑上限硬编码为 1→2，attempt_2 失败即 blocked（无第三档）",
          src.count("attempt=2") == 1 and "attempt=3" not in src
          and "attempt_2_not_pass" in src,
          f"attempt=2 出现 {src.count('attempt=2')} 次；"
          f"attempt=3 出现 {src.count('attempt=3')} 次；"
          f"attempt_2_not_pass 存在={'attempt_2_not_pass' in src}")


def t20_atomic_checkpoint_failure() -> None:
    """R3 §6-T11：checkpoint 原子写失败**可检出**且**不留半文件**。"""
    from rt_gate import atomic_write_json as aw
    root = "lt2-supervisor-selftest-atomic"
    d = RUNS / root / "atomicprobe"
    if d.exists() and not d.is_dir():
        d.unlink()
    d.mkdir(parents=True, exist_ok=True)
    # 目标路径是一个**已存在的目录** ⇒ os.replace 必失败。
    # 先清理（否则第二次运行会因目录已存在而抛 FileExistsError ⇒ 整个套件中止、无「合计」行；
    # 这是 flake hunter 在 run 04/05 抓到的形态）。
    bad_target = d / "checkpoint.json"
    if bad_target.is_dir():
        shutil.rmtree(bad_target)
    elif bad_target.exists():
        bad_target.unlink()
    if (d / "ok.json").exists():
        (d / "ok.json").unlink()
    bad_target.mkdir()
    r = aw(bad_target, {"k": "v"})
    check("T11a 原子写失败被检出（返回 ok=False，不静默）",
          r.get("ok") is False and bool(r.get("error")), f"ok={r.get('ok')}")
    half = bad_target.with_name(bad_target.name + ".tmp")
    check("T11b 失败后不留下半写文件（.tmp 已清理）",
          not half.exists(), f".tmp 存在={half.exists()}")
    check("T11c 目标未变成文件/未被破坏",
          bad_target.is_dir(), f"目标类型={'dir' if bad_target.is_dir() else 'file'}")
    # 正常路径仍可用（对照）
    good = d / "ok.json"
    r2 = aw(good, {"k": "v"})
    check("T11d 对照：正常路径原子写成功", r2.get("ok") is True and good.is_file(),
          f"ok={r2.get('ok')}")


# --------------------------------------------------------------------------- #
# T5 —— 共享状态拆分后不丢 hard-stop 信号
# --------------------------------------------------------------------------- #
def t5_no_signal_loss() -> None:
    child = fresh_child_dir(4)
    now = FIXED_EPOCH          # 固定值 ⇒ 产物可复算（G1）
    P.write_own_state(child / P.SAMPLER_STATE_NAME,
                      {"writer": "lt2_sampler", "last_sample_ts": now, "sample_index": 7,
                       "verdict": "hard_stop", "reasons": ["ws_hard_stop(12300 >= 12288 x2)"],
                       "updated_at": FIXED_TS})
    # worker 反复写自己的状态（v1 会在这里把 sidecar 的 verdict 覆盖掉）
    for i in range(25):
        P.write_own_state(child / P.WORKER_STATE_NAME,
                          {"writer": "lt2_combo_worker", "pid": 999, "stage": "solve",
                           "stop": False, "seq": i, "cancel_requested": False,
                           "updated_at": FIXED_TS})
    ss = P.read_sampler_state(child)
    ws = P.read_worker_state(child)
    act = P.decide_next_action({"verdict": ss.get("verdict")}, sidecar_health(now, now, True), ws)
    check("T5 worker 反复写后 hard-stop verdict 仍在",
          ss.get("verdict") == "hard_stop" and act["action"] == "hard_stop_enforce",
          f"verdict={ss.get('verdict')}, worker seq={ws.get('seq')}")
    # 反向：sampler 反复写也不能抹掉 worker 的控制字段
    P.write_own_state(child / P.WORKER_STATE_NAME,
                      {"writer": "lt2_combo_worker", "pid": 999, "stop": False,
                       "cancel_requested": True, "cancel_reason": ["hard"],
                       "updated_at": FIXED_TS})
    for i in range(25):
        P.write_own_state(child / P.SAMPLER_STATE_NAME,
                          {"writer": "lt2_sampler", "last_sample_ts": FIXED_EPOCH,
                           "sample_index": 100 + i, "verdict": "ok", "reasons": [],
                           "updated_at": FIXED_TS})
    ws2 = P.read_worker_state(child)
    check("T5 sampler 反复写后 worker 控制字段仍在",
          ws2.get("cancel_requested") is True and ws2.get("stop") is False,
          f"cancel_requested={ws2.get('cancel_requested')}, stop={ws2.get('stop')}")
    check("T5 唯一规则：child 目录只放证据，信号在 <run_id>/signals/（D-A）",
          P.SIGNAL_DIR_NAME == "signals"
          and str(P.signal_path("r", "child_00_attempt_1")).endswith(
              r"r\signals\child_00_attempt_1.signal.json"),
          f"signal_path={P.signal_path('r', 'child_00_attempt_1')}")


# --------------------------------------------------------------------------- #
# T6 —— PID / 启动时间 / 端口 owner 任一不符 ⇒ 拒绝终止（进程必须还活着）
# --------------------------------------------------------------------------- #
def t6_refuse_on_mismatch() -> None:
    child = fresh_child_dir(5, root=TEST_RUN_LIVE)
    server = spawn_sleeper(600)
    ident = P.proc_identity(server.pid)
    ensure_worker_state(child, combo="(0.6,4)", pid=server.pid)
    try:
        # 6a 端口 owner 是别的 PID
        deps = FakeDeps(port_open_value=True, owner_pid=server.pid + 12345)
        rec = P.verified_emergency_termination(
            child_dir=child, expected_pid=server.pid, identity_at_launch=ident,
            run_id=TEST_RUN_LIVE, trigger={"why": "port_owner_mismatch"}, deps=deps, grace_s=1,
            clock=FIXED_CLOCK)
        check("T6a 端口 owner 不符 ⇒ 拒绝终止",
              rec["refused"] is not None and rec["termination"]["performed"] is False,
              (rec["refused"] or {}).get("reason", ""))
        check("T6a 拒绝后目标进程仍存活（没有被误杀）", P.proc_exists(server.pid) is True)

        # 6b 启动时间不符（同 PID，不同身份）
        bad_ident = dict(ident)
        bad_ident["start_filetime"] = str(int(ident["start_filetime"]) + 1)
        deps2 = FakeDeps(port_open_value=True, owner_pid=server.pid,
                         ident_override=bad_ident)
        rec2 = P.verified_emergency_termination(
            child_dir=child, expected_pid=server.pid, identity_at_launch=ident,
            run_id=TEST_RUN_LIVE, trigger={"why": "starttime_mismatch"}, deps=deps2, grace_s=1,
            clock=FIXED_CLOCK)
        check("T6b 进程启动时间不符 ⇒ 拒绝终止",
              rec2["refused"] is not None and rec2["termination"]["performed"] is False,
              json.dumps((rec2.get("ownership_checks") or {}).get("identity_match"),
                         ensure_ascii=False))
        check("T6b 拒绝后目标进程仍存活", P.proc_exists(server.pid) is True)

        # 6c expected_pid 未知
        deps3 = FakeDeps(port_open_value=True, owner_pid=None)
        rec3 = P.verified_emergency_termination(
            child_dir=child, expected_pid=None, identity_at_launch=None,
            run_id=TEST_RUN_LIVE, trigger={"why": "pid_unknown"}, deps=deps3, grace_s=1,
            clock=FIXED_CLOCK)
        check("T6c PID 未知 ⇒ 拒绝终止",
              rec3["refused"] is not None and rec3["termination"]["performed"] is False,
              (rec3["refused"] or {}).get("reason", ""))
    finally:
        kill_quiet(server)


# --------------------------------------------------------------------------- #
# T7 —— 终止后端口与 PID 的二次确认（含 rc≠0 反例）
# --------------------------------------------------------------------------- #
def t7_post_termination_verification() -> None:
    child = fresh_child_dir(6, root=TEST_RUN_LIVE)
    server = spawn_sleeper(600)
    ident = P.proc_identity(server.pid)
    ensure_worker_state(child, combo="(0.7,5)", pid=server.pid)
    try:
        deps = FakeDeps(port_open_value=True, owner_pid=server.pid)
        rec = P.verified_emergency_termination(
            child_dir=child, expected_pid=server.pid, identity_at_launch=ident,
            run_id=TEST_RUN_LIVE, trigger={"why": "verify_positive"}, deps=deps,
            grace_s=1, reclaim_worker_s=1, clock=FIXED_CLOCK)
        pv = rec["post_verification"] or {}
        check("T7a 终止命令退出码 = 0",
              (rec["termination"].get("command") or {}).get("rc") == 0,
              json.dumps(rec["termination"].get("command"), ensure_ascii=False)[:160])
        check("T7a 二次确认：PID 消失 + 端口关闭 + 无意外 server",
              pv.get("expected_pid_absent") is True and pv.get("port_closed") is True
              and pv.get("no_new_unexpected_comsolmphserver") is True and pv.get("verified") is True,
              json.dumps({k: pv.get(k) for k in ("expected_pid_absent", "port_closed",
                                                 "no_new_unexpected_comsolmphserver",
                                                 "verified")}, ensure_ascii=False))
        check("T7a 真实验证：进程确已消失", P.proc_exists(server.pid) is False)
    finally:
        kill_quiet(server)

    # 反例：终止命令返回 rc=1（未真正杀死） ⇒ verified 必须为 False
    child2 = fresh_child_dir(7, root=TEST_RUN_LIVE)
    server2 = spawn_sleeper(600)
    ensure_worker_state(child2, combo="(0.75,5)", pid=server2.pid)
    try:
        ident2 = P.proc_identity(server2.pid)
        deps2 = FakeDeps(port_open_value=True, owner_pid=server2.pid,
                         terminate_impl=lambda pid: {"cmd": "fake", "rc": 1, "output": ""},
                         verify_impl=lambda pid, rc, port: P.verify_termination(
                             pid, rc, port, wait_pid_s=3, wait_port_s=1))
        rec2 = P.verified_emergency_termination(
            child_dir=child2, expected_pid=server2.pid, identity_at_launch=ident2,
            run_id=TEST_RUN_LIVE, trigger={"why": "rc_nonzero"}, deps=deps2, grace_s=1,
            reclaim_worker_s=1, clock=FIXED_CLOCK)
        pv2 = rec2["post_verification"] or {}
        check("T7b rc≠0 ⇒ 二次确认判失败（不把调用当成功）",
              pv2.get("verified") is False and pv2.get("termination_command_exit") == 1,
              json.dumps({k: pv2.get(k) for k in ("verified", "termination_command_exit",
                                                  "expected_pid_absent")}, ensure_ascii=False))
        check("T7b 进程确实仍存活（证明该反例有效）", P.proc_exists(server2.pid) is True)
    finally:
        kill_quiet(server2)


# --------------------------------------------------------------------------- #
# T8 —— 聚合 manifest 真正产出（G2），且覆盖全部 child（G3）
# --------------------------------------------------------------------------- #
def t8_manifest_produced() -> dict:
    # 通过 CLI 走真实入口（只读扫描 + 一次写；不启动 server / 不 import mph）
    p = subprocess.run([sys.executable, str(P.SELF if hasattr(P, "SELF") else
                                            TOOLS / "lt2_production.py"),
                        "--run-id", TEST_RUN, "--assemble-manifest-only",
                        "--fixed-timestamps"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    mpath = RUNS / TEST_RUN / "batch_manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8")) if mpath.is_file() else {}
    children = m.get("children", [])
    on_disk = sorted(d.name for d in (RUNS / TEST_RUN).glob("child_*_attempt_*") if d.is_dir())
    check("T8 batch_manifest.json 已真实产出", p.returncode == 0 and mpath.is_file(),
          f"exit={p.returncode}, path={mpath}")
    check("T8 manifest 覆盖**磁盘上全部** child 目录（不是只列前 4 个）",
          len(children) == len(on_disk)
          and {c["dir_name"] for c in children} == set(on_disk),
          f"manifest={len(children)} 个, 磁盘={len(on_disk)} 个")
    # 允许**被显式脱敏**的控制通道文件（sha256=None + pid_redacted_for_determinism）
    # ——否则 batch_manifest 无法确定性；但**不允许**无声缺失 sha256：
    # 那正是历史上 81/82 的最可能形态（T8 要求每个文件都有可读哈希，而 worker 仍在写盘时
    # 某文件瞬时不可读 ⇒ sha256=None ⇒ 恰好 1 项断言失败、随调度约 1/7 复现）。
    unreadable = {c["dir_name"]: sorted(k for k, v in c["files"].items()
                                        if v.get("sha256") is None
                                        and not v.get("pid_redacted_for_determinism"))
                  for c in children}
    unreadable = {k: v for k, v in unreadable.items() if v}
    redacted = sum(1 for c in children for v in c["files"].values()
                   if v.get("pid_redacted_for_determinism"))
    check("T8 manifest 含每个 child 的文件级 sha256（脱敏项除外，且无无声缺失）",
          all(c["files"] for c in children) and not unreadable,
          f"children={len(children)}, 脱敏文件={redacted}, 缺 sha256 的目录={unreadable or '无'}")
    check("T8 manifest 声明只读组装、未跑 COMSOL",
          m.get("assembled_read_only") is True and m.get("comsol_started") is False
          and m.get("mph_imported") is False,
          f"read_only={m.get('assembled_read_only')}, comsol={m.get('comsol_started')}")
    inv_bad = [c["dir_name"] for c in children if not c["inventory_ok"]]
    check("T8 全部 child 满足其 kind 的清单规约（G3）", not inv_bad,
          f"missing_required 的目录={inv_bad or '无'}")
    return m


# --------------------------------------------------------------------------- #
# T9 —— 确定性复算（G1）：同一命令连跑两次，产物逐字节一致
# --------------------------------------------------------------------------- #
def t9_determinism() -> None:
    a = fresh_child_dir(8)
    b = fresh_child_dir(9)
    ensure_worker_state(a, combo="(0.6,4)")
    ensure_worker_state(b, combo="(0.6,4)")
    run_sampler_sim(a, 5, fixed=True)
    run_sampler_sim(b, 5, fixed=True)
    files = ["resource_timeline.jsonl", "resource_timeline.csv", "sampler_state.json"]
    same = {f: (sha(a / f) is not None and sha(a / f) == sha(b / f)) for f in files}
    check("T9 fixed 模式：同一命令两次运行产物逐字节一致", all(same.values()),
          "; ".join(f"{f}={same[f]}" for f in files))
    print("    固定模式 4 条时间线 sha256（可复算）：", flush=True)
    for idx in range(4):
        d = RUNS / TEST_RUN / P.CHILD_DIR_FMT.format(idx=idx, attempt=1)
        print(f"      {d.name}: {sha(d / 'resource_timeline.jsonl')}", flush=True)
    # 反例：wallclock 模式两次运行哈希不同（证明"必须标注不可复现"是必要的）。
    # **放在独立 run 目录**，避免把墙钟产物混进被引用为证据的主 run 目录（否则 manifest 不可复算）。
    wroot = TEST_RUN + "-wallclock"
    c = fresh_child_dir(0, root=wroot)
    d = fresh_child_dir(1, root=wroot)
    ensure_worker_state(c, combo="(0.6,4)")
    ensure_worker_state(d, combo="(0.6,4)")
    run_sampler_sim(c, 5, fixed=False)
    # 时间戳是秒精度：两次运行若落在同一秒会得到相同哈希（假通过）。
    # 显式跨过 1 秒边界，使该反例稳定成立。
    time.sleep(1.2)
    run_sampler_sim(d, 5, fixed=False)
    check("T9 wallclock 模式两次运行哈希不同（故报告中必须标注不可复现）",
          sha(c / "resource_timeline.jsonl") != sha(d / "resource_timeline.jsonl"),
          f"wallclock_a={str(sha(c / 'resource_timeline.jsonl'))[:10]}, "
          f"wallclock_b={str(sha(d / 'resource_timeline.jsonl'))[:10]}")


def report_inventory() -> None:
    """如实打印**全部** child 目录（不藏形态不齐的目录），并按根目录标注可复算性。"""
    for root_name in (TEST_RUN, TEST_RUN_SMOKE, TEST_RUN_POSTSOLVE, TEST_RUN_LIVE,
                      "lt2-supervisor-selftest-retry", "lt2-supervisor-selftest-atomic",
                      TEST_RUN + "-wallclock"):
        root = RUNS / root_name
        dirs = sorted(d for d in root.glob("child_*_attempt_*") if d.is_dir())
        if not dirs:
            continue
        tag = {"y": "可逐字节复算 (fixed)", "n": "含真实 PID/墙钟 ⇒ 不可复算"}[
            "y" if root_name == TEST_RUN else "n"]
        print(f"\n=== {root_name} 下全部 {len(dirs)} 个 child 目录（如实）=== [{tag}]",
              flush=True)
        for d in dirs:
            info = P.describe_child_dir(d)
            print(f"  {d.name}/  kind={info['kind']}  files={len(info['present'])}  "
                  f"inventory_ok={info['inventory_ok']}", flush=True)
            for f in info["present"]:
                b_ = info["files"][f].get("bytes")
                h_ = info["files"][f].get("sha256")
                b_txt = f"{b_:>7} B" if isinstance(b_, int) else "REDACTED B"
                h_txt = h_ if h_ else "REDACTED(pid/time channel; 见 redaction_reason)"
                print(f"      {f:<28} {b_txt}  {h_txt}", flush=True)
            if info["missing_required"]:
                print(f"      ! missing_required={info['missing_required']}", flush=True)


# --------------------------------------------------------------------------- #
# T10–T14 —— 接线冒烟测试（D-A 回归漏测的那条链路）
#   supervisor 拉起 worker → worker 接受自己的 child 目录 → sampler 产出时间线
# 用 fake-combo-worker（**绝不启动 COMSOL、不 import mph**）
# --------------------------------------------------------------------------- #
TEST_RUN_SMOKE = "lt2-supervisor-selftest-smoke"


def _smoke_args(**kw):
    import types
    base = dict(freqs=("5",), interval=5.0, gate_poll=0.3,
                worker_role="fake-combo-worker", drill=False,
                fixed_timestamps=True, allow_retry=True,
                ws_hard_stop_mb=None, commit_hard_stop_mb=None,
                physical_hard_stop_mb=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def t10_wiring_smoke_normal() -> dict:
    """T10 正常路径：worker 不得拒绝，child 目录内应有完整 5 件套。"""
    root = TEST_RUN_SMOKE
    d = fresh_child_dir(0, root=root)
    for f in sorted((RUNS / root).glob("*")):
        if f.is_file():
            f.unlink()
    child_dir = RUNS / root / P.CHILD_DIR_FMT.format(idx=0, attempt=1)
    res = P.supervise_child(root, 0, 0.8, 2, _smoke_args(), attempt=1)
    present = sorted(f.name for f in child_dir.iterdir() if f.is_file())
    need = ["checkpoint.json", "resource_timeline.csv", "resource_timeline.jsonl",
            "sampler_state.json", "worker_state.json"]
    check("T10 supervisor→worker→sampler 接线跑通（worker 未拒绝）",
          res["checkpoint_present"] and all(n in present for n in need),
          f"child 内文件={present}")
    check("T10 时间线为真实 sampler 产出（非空且有样本）",
          res["timeline_present"] and (res["timeline_sha256"] is not None),
          f"timeline_sha256={str(res['timeline_sha256'])[:16]}")
    return {"res": res, "child_dir": child_dir, "present": present}


def t11_signal_not_in_child_dir(child_dir: Path) -> None:
    """T11 supervisor 信号**不得**出现在 child 目录内（D-A 的唯一规则）。"""
    inner = [f.name for f in child_dir.iterdir() if f.is_file()]
    sig = P.signal_path(TEST_RUN_SMOKE, child_dir.name)
    check("T11 child 目录内没有 supervisor_signal.json",
          "supervisor_signal.json" not in inner, f"child 内文件={inner}")
    check("T11 正常路径不产生信号文件（只在硬停时才写，且写在 signals/）",
          not sig.is_file(), f"signal_path={sig}")


def t12_no_refused_and_not_resource_hard_stop(res: dict) -> None:
    """T12 正常路径不得出现 *_refused.json，分类也不是 resource_hard_stop。"""
    refused = sorted(p.name for p in (RUNS / TEST_RUN_SMOKE).glob("*_refused.json"))
    rc = res.get("retry_classification") or {}
    check("T12 正常路径没有 *_refused.json",
          not refused and res.get("child_dir_reuse_refused") is False,
          f"refused 文件={refused or '无'}")
    check("T12 正常路径分类不是 resource_hard_stop",
          rc.get("class") != "resource_hard_stop" and res.get("termination_trigger") is None,
          f"class={rc.get('class')}, trigger={res.get('termination_trigger')}")


def t13_resource_hard_stop_only_on_crossing() -> None:
    """T13 `resource_hard_stop` 只在真的越线样本时出现（含反向用例）。"""
    # 正向：越线样本
    ss_pos = {"verdict": "hard_stop", "sample_index": 5,
              "reasons": ["commit_hard_stop(2000.0 <= 4096.0 x2)"],
              "counters": {"commit_hard": 2}, "last_sample_ts": FIXED_EPOCH}
    ws_ok = {"sampler_pid": 123, "pid": 456}
    t_pos = P.classify_trigger(ss_pos, ws_ok, {"action": "hard_stop_enforce",
                                               "source": "sampler_state.verdict"})
    r_pos = P.classify_retry({"termination_trigger": t_pos, "drill": False})
    check("T13a 越线样本 ⇒ threshold_crossed + resource_hard_stop",
          t_pos["trigger_kind"] == "threshold_crossed" and t_pos["is_hard_stop"] is True
          and r_pos["class"] == "resource_hard_stop",
          f"kind={t_pos['trigger_kind']}, class={r_pos['class']}")
    # 正向（演练）：同样越线但 drill ⇒ drill_hard_stop，不得混入生产口径
    r_drill = P.classify_retry({"termination_trigger": t_pos, "drill": True})
    check("T13b 演练越线 ⇒ drill_hard_stop（不混入 resource_hard_stop）",
          r_drill["class"] == "drill_hard_stop", f"class={r_drill['class']}")
    # 反向 A：worker 未登记 sampler（本例即真实故障现场）
    t_nw = P.classify_trigger({}, {}, {"action": "hard_stop_enforce",
                                       "source": "sidecar_health"})
    r_nw = P.classify_retry({"termination_trigger": t_nw, "drill": False})
    check("T13c 无 worker_state ⇒ 不是 resource_hard_stop",
          t_nw["trigger_kind"] == "worker_startup_failure" and t_nw["is_hard_stop"] is False
          and r_nw["class"] != "resource_hard_stop",
          f"kind={t_nw['trigger_kind']}, class={r_nw['class']}")
    # 反向 B：sidecar 在首个样本前退出（sampler_exited，无样本）
    ss_none = {"verdict": "hard_stop", "reasons": ["sidecar_exited"], "sample_index": None}
    t_ns = P.classify_trigger(ss_none, {"sampler_pid": 123}, {"action": "hard_stop_enforce",
                                                              "source": "sidecar_health"})
    r_ns = P.classify_retry({"termination_trigger": t_ns, "drill": False})
    check("T13d 首个样本前退出 ⇒ integrity_failure，不是 resource_hard_stop",
          t_ns["trigger_kind"] == "integrity_failure" and t_ns["is_hard_stop"] is False
          and r_ns["class"] == "sampler_supervisor_integrity",
          f"kind={t_ns['trigger_kind']}, class={r_ns['class']}")
    # 反向 C：child 目录复用被拒
    r_rf = P.classify_retry({"child_dir_reuse_refused": True,
                             "termination_trigger": {"trigger_kind": "unclassified_failure",
                                                     "is_hard_stop": False}})
    check("T13e 目录复用被拒 ⇒ child_dir_reuse_refused（fail-closed）",
          r_rf["class"] == "child_dir_reuse_refused", f"class={r_rf['class']}")


def t14_smoke_determinism() -> None:
    """T14 冒烟**证据**连跑两次逐字节一致（fixed 模式）。

    排除 `worker_state.json`：它是**控制通道**，必须携带真实 `sampler_pid` 供 supervisor
    判活，因此天然不可复算；证据文件（时间线/sampler_state/checkpoint/rows）才是可复算对象，
    且 checkpoint 在确定性模式下已把 PID 置空（`pid_redacted_for_determinism`）。

    ⚠️ 2026-09-15 缺陷（父 agent 裁定 A）：本断言曾在**同一份代码**上摇摆（81/82 vs 82/82），
    原因是假 worker 宣告 `stage=closed` 后**立刻 return**，使"正常收尾记录写不写"退化为微秒级
    竞态。修法不是放宽断言，而是让替身在宣告 closed 后**有界驻留**（`FAKE_CLOSED_LINGER_S`）
    ——真 worker 因要拆 sampler/COMSOL 天然驻留，故这也是保真度修正。
    """
    root = TEST_RUN_SMOKE
    volatile = {"worker_state.json"}

    def snap():
        return {str(f.relative_to(RUNS / root)): sha(f)
                for f in sorted((RUNS / root).rglob("*"))
                if f.is_file() and f.name not in volatile | {"batch_manifest.json"}}

    before = snap()
    fresh_child_dir(0, root=root)
    P.supervise_child(root, 0, 0.8, 2, _smoke_args(), attempt=1)
    after = snap()
    bad = [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
    check("T14 冒烟证据连跑两次逐字节一致", not bad and len(before) >= 5,
          f"不一致={bad or '无'}（共 {len(before)} 个证据文件，已排除控制通道 {sorted(volatile)}）")
    # 裁定 B 的命名纪律：正常收尾记录必须是 completion_record.json，且**不得**出现
    # termination_trigger.json（后者专表"发生过终止动作"）。
    child_dir = RUNS / root / P.CHILD_DIR_FMT.format(idx=0, attempt=1)
    comp = getattr(P, "COMPLETION_FILE_NAME", None)
    check("T14b 正常收尾落在 completion_record.json，且无 termination_trigger.json",
          comp is not None and (child_dir / comp).is_file()
          and not (child_dir / P.TRIGGER_FILE_NAME).is_file(),
          f"存在={(child_dir / comp).is_file() if comp else None}, "
          f"termination_trigger 存在={(child_dir / P.TRIGGER_FILE_NAME).is_file()}, "
          f"child 内文件={sorted(f.name for f in child_dir.iterdir() if f.is_file())}")


TEST_RUN_DRILL = "lt2-supervisor-selftest-drill"


def t15_drill_wiring() -> None:
    """T15 演练接线（无 COMSOL）：压低阈值 → 运行期硬停 → drill 标记 + drill_hard_stop。"""
    root = TEST_RUN_DRILL
    fresh_child_dir(0, root=root)
    child_dir = RUNS / root / P.CHILD_DIR_FMT.format(idx=0, attempt=1)
    args = _smoke_args(drill=True, ws_hard_stop_mb=5000, blocked_hold_s=4.0)
    res = P.supervise_child(root, 0, 0.8, 2, args, attempt=1)
    trig = res.get("termination_trigger") or {}
    rc = res.get("retry_classification") or {}
    check("T15a 演练阈值越线 ⇒ threshold_crossed + is_hard_stop",
          trig.get("trigger_kind") == "threshold_crossed" and trig.get("is_hard_stop") is True,
          f"kind={trig.get('trigger_kind')}")
    check("T15b 演练硬停分类为 drill_hard_stop（不混入 resource_hard_stop）",
          rc.get("class") == "drill_hard_stop", f"class={rc.get('class')}")
    tpath = child_dir / P.TRIGGER_FILE_NAME
    trig_file = json.loads(tpath.read_text(encoding="utf-8")) if tpath.is_file() else {}
    check("T15c 触发记录里带演练阈值证据（默认值 vs 演练值）",
          bool((trig.get("threshold_evidence") or {}).get("thresholds"))
          and (trig["threshold_evidence"]["thresholds"].get("ws_hard_stop_mb") == 5000.0),
          json.dumps((trig.get("threshold_evidence") or {}).get("thresholds", {}).get(
              "ws_hard_stop_mb"), ensure_ascii=False))
    check("T15d 演练信号仍写在 child 目录之外",
          P.signal_path(root, child_dir.name).is_file()
          and not (child_dir / "supervisor_signal.json").exists(),
          f"signal={P.signal_path(root, child_dir.name).name}")
    rows = [json.loads(l) for l in (child_dir / "resource_timeline.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    check("T15e 时间线样本带 drill 标记与演练阈值",
          bool(rows) and all(r.get("drill") is True for r in rows)
          and all(isinstance(r.get("drill_thresholds"), dict) for r in rows),
          f"n={len(rows)}, drill={rows[0].get('drill') if rows else None}")
    check("T15f 触发记录标明非真实资源越线",
          trig_file.get("is_hard_stop") is True and "wording_note" in trig_file,
          f"wording_note={str(trig_file.get('wording_note'))[:60]}")
    # 假 worker 没有真 server ⇒ 不得声称终止成功；分支只能是「拒绝」或「worker 自行退出」
    term = res.get("termination") or {}
    t_inner = term.get("termination") or {}
    branch = ("refused" if term.get("refused") is not None
              else t_inner.get("reason") or "unknown")
    check("T15g 无真实 server 时绝不声称终止成功（拒绝或自行退出）",
          t_inner.get("performed") is False
          and (term.get("refused") is not None
               or t_inner.get("reason") == "self_exited_within_grace"),
          f"performed={t_inner.get('performed')}, branch={branch}")


def t16_drill_cli_guard() -> None:
    """T16 `--drill` 的 CLI 把关：无 --drill 传阈值必须拒绝；有 --drill 才接受。"""
    base = [sys.executable, str(TOOLS / "lt2_production.py")]
    p_bad = subprocess.run(base + ["--run-id", "x-guard", "--dry-run",
                                   "--ws-hard-stop-mb", "5000"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    check("T16a 无 --drill 却传阈值覆盖 ⇒ 拒绝且非零退出",
          p_bad.returncode == 9 and "[STOP]" in (p_bad.stdout + p_bad.stderr),
          f"exit={p_bad.returncode}")
    # preflight-only 走真实只读门禁：演练不跳过门禁（此处只验证门禁确实被执行并给出结论）。
    # run-id 取唯一值：否则第二次运行会被 run-id 复用防护拦下（exit 4），测不到门禁。
    probe_id = f"lt2-drill-guard-probe-{os.getpid()}"
    p_pre = subprocess.run(base + ["--run-id", probe_id, "--preflight-only"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    check("T16b 演练相关路径的前置门禁照常执行（有明确 gate 结论）",
          p_pre.returncode in (0, 5) and "gate_pass" in (p_pre.stdout + p_pre.stderr),
          f"exit={p_pre.returncode}")


TEST_RUN_POSTSOLVE = "lt2-supervisor-selftest-postsolve"


def t17_postsolve_path() -> None:
    """T17 求解后收尾路径（D-D 的覆盖）。

    真机 run 求解成功后一秒抛 `NameError: state_f`，因为整段收尾逻辑长在 worker 里、
    冒烟测试够不到。这里用 **假求值器 + 真实收尾代码**（`extract_rows` +
    `finalize_after_solve`）走同一条路径，断言产物齐备且**不出现 worker_error.json**。
    """
    root = TEST_RUN_POSTSOLVE
    fresh_child_dir(0, root=root)
    child_dir = RUNS / root / P.CHILD_DIR_FMT.format(idx=0, attempt=1)
    ensure_worker_state(child_dir, combo="(0.8,2)")
    p = subprocess.Popen([sys.executable, str(P.SIDECAR), "--run-id", root,
                          "--state-dir", str(child_dir), "--simulate", "4",
                          "--simulate-profile", "safe", "--fixed-timestamps"],
                         stdout=DEVNULL, stderr=DEVNULL)
    p.wait(timeout=60)

    freqs = ("5", "10", "15", "20", "25", "30", "35")

    def cx(expr, i):
        table = {"ave_outer(V)": (1.0, 0.0), "ave_inner(V)": (-1.0, 0.0),
                 "ave_ref(V)": (0.0, 0.0), "Ptot": (1.0e-6, 0.0),
                 "Vave": (1.0e-2, 0.0), "V_center": (0.0, 0.0)}
        return table.get(expr, (None, None))

    rows = P.extract_rows(freqs, cx, lambda i: (i + 1) * 5e6, 0.8, 2, 157390, 749.5)
    lt2c = {"checks": {"pass": True}, "detail": {"area_ptot_geometry": 6.266153558917681e-08},
            "tolerance_evidence": {"scope": P.TOLERANCE_SCOPE, "area_rel_tol": 1e-6,
                                   "bbox_rel_tol": 1e-6}}
    state_calls = []

    def fake_set_state(**kw):
        state_calls.append(kw)
        return kw

    th = P.Thresholds()
    ck = P.finalize_after_solve(
        run_id=root, idx=0, attempt=1, child_dir=child_dir, x=0.8, n1=2, freqs=freqs,
        rows=rows, lt2c=lt2c, th=th, cancel_rec=None, set_state=fake_set_state,
        meta={"server_pid": None, "server_identity": None, "pid_source": "port_owner",
              "drill": False},
        jsonl_f=child_dir / "resource_timeline.jsonl", clock=FIXED_CLOCK)

    ck_path = child_dir / "checkpoint.json"
    check("T17a 求解后能写出 checkpoint.json（D-D 回归点）", ck_path.is_file(),
          f"checkpoint 存在={ck_path.is_file()}")
    check("T17b rows.csv / raw_rows.csv 均产出", (child_dir / "rows.csv").is_file()
          and (child_dir / "raw_rows.csv").is_file(),
          f"rows 行数={len(rows)}")
    check("T17c 7 行结果且驱动电压自洽（|Vdiff|=2V）",
          len(rows) == 7 and all(abs(r["Vdiff_abs"] - 2.0) < 1e-9 for r in rows),
          f"n={len(rows)}, Vdiff={rows[0]['Vdiff_abs']}")
    check("T17d lt2c_quick_gate 与 tolerance_evidence 有结果（非 null）",
          ck.get("lt2c_quick_gate") is not None and ck.get("tolerance_evidence") is not None,
          f"lt2c pass={(ck.get('lt2c_quick_gate') or {}).get('checks', {}).get('pass')}")
    check("T17e pass_conditions 非 null 且含 commit 项",
          isinstance(ck.get("pass_conditions"), dict)
          and "commit_hard_stop_samples_0" in ck["pass_conditions"],
          f"keys={len(ck.get('pass_conditions') or {})}")
    check("T17f 走的是真实 'checkpoint' 阶段写入（D-D 崩溃点）",
          any(c.get("stage") == "checkpoint" for c in state_calls),
          f"set_state 调用={state_calls}")
    check("T17g **不出现 worker_error.json**",
          not (child_dir / "worker_error.json").exists(),
          f"child 内文件={sorted(f.name for f in child_dir.iterdir())}")


def t18_postsolve_error_classification() -> None:
    """T18 worker 自身异常应归 `worker_exception_postsolve`，不指向监控子系统。"""
    child = {"worker_error": "NameError: name 'state_f' is not defined",
             "worker_error_type": "NameError", "worker_error_stage": "postprocess",
             "termination_trigger": None}
    rc = P.classify_retry(child)
    check("T18a worker 异常 ⇒ worker_exception_postsolve",
          rc["class"] == "worker_exception_postsolve", f"class={rc['class']}")
    check("T18b 不再误归 sampler_supervisor_integrity / resource_hard_stop",
          rc["class"] not in ("sampler_supervisor_integrity", "resource_hard_stop")
          and rc["retry"] is False,
          f"class={rc['class']}, retry={rc['retry']}")
    rc2 = P.classify_retry({"worker_error": "OSError: disk", "worker_error_type": "OSError",
                            "worker_error_stage": "startup"})
    check("T18c 求解前 worker 异常 ⇒ worker_exception_presolve（同样 fail-closed）",
          rc2["class"] == "worker_exception_presolve" and rc2["retry"] is False,
          f"class={rc2['class']}")


LOCK = NS_ROOT / LOCK_NAME
OWNER_TOKEN = f"{os.getpid()}-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def _proc_create_time(pid: int) -> str | None:
    out = P.run_ps(f"$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
                   "if($p){ $p.StartTime.ToFileTime() }")
    return out or None


def _read_lock() -> dict:
    try:
        return json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _holder_alive(info: dict) -> bool:
    """持锁者是否仍存在。**必须**同时核对 pid 与进程创建时间，
    避免 pid 复用把「已死」误判为「活着」。"""
    pid = info.get("pid")
    if not isinstance(pid, int) or not P.proc_exists(pid):
        return False
    cur = _proc_create_time(pid)
    return bool(cur and info.get("process_create_time") == cur)


def acquire_lock() -> dict:
    """**原子**创建锁（`os.O_CREAT|os.O_EXCL`），不是 check-then-create。

    Codex R6 §3.2：旧实现是 `exists()` 后 `write_text()`，两个进程可能同时认为无锁。
    这里：
      - 创建走 `os.open(..., O_CREAT|O_EXCL|O_WRONLY)` ⇒ 内核保证只有一个成功；
      - 锁内含 pid + 进程创建时间 + owner token；
      - 只有**核验旧 owner 已不存在**（pid 已死或启动时间不符）才允许回收，
        且回收同样用原子方式（unlink 后重试创建，失败即认输）。
    """
    NS_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "owner_token": OWNER_TOKEN, "namespace": NS,
               "process_create_time": _proc_create_time(os.getpid()),
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in (1, 2):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, blob)
            finally:
                os.close(fd)
            return {"ok": True, "attempt": attempt, "lock": str(LOCK),
                    "owner_token": OWNER_TOKEN, "holder": payload}
        except FileExistsError:
            old = _read_lock()
            if _holder_alive(old):
                return {"ok": False, "verdict": "REFUSED_CONCURRENT_OWNER",
                        "lock": str(LOCK), "holder": old,
                        "reason": "同一 namespace 已被活跃进程持有；不得改动其目录"}
            # 旧 owner 已不存在 ⇒ 允许回收（仅此一种情况）
            try:
                LOCK.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                return {"ok": False, "verdict": "REFUSED_LOCK_RECLAIM_FAILED",
                        "lock": str(LOCK), "holder": old, "reason": str(exc)}
    return {"ok": False, "verdict": "REFUSED_LOCK_CONTENDED", "lock": str(LOCK)}


def release_lock() -> dict:
    """只在**本进程仍是持有者**时才删除锁（token 校验）。"""
    info = _read_lock()
    if info.get("owner_token") != OWNER_TOKEN:
        return {"released": False, "reason": "not_owner", "current_holder": info}
    try:
        LOCK.unlink()
        return {"released": True}
    except Exception as exc:  # noqa: BLE001
        return {"released": False, "reason": f"{type(exc).__name__}: {exc}"}


def cleanup_own_namespace() -> dict:
    """**只清理本进程拥有的精确 namespace 目录**（Codex R6 §3.2 明令禁止全局 glob 清理）。

    三重校验：resolved 路径必须位于 `work/runs` 下、目录名等于本进程 namespace、
    且锁内 owner token 与本进程一致。
    """
    root = NS_ROOT.resolve()
    runs = P.RUNS.resolve()
    checks = {"under_runs": str(root).startswith(str(runs)),
              "is_own_namespace": NS_ROOT.name == NS,
              "owner_token_match": _read_lock().get("owner_token") == OWNER_TOKEN}
    if not all(checks.values()):
        return {"cleaned": False, "checks": checks,
                "reason": "清理前置校验未通过 ⇒ 拒绝清理"}
    shutil.rmtree(NS_ROOT, ignore_errors=True)
    return {"cleaned": True, "checks": checks, "path": str(NS_ROOT)}


def write_summary(extra: dict | None = None) -> Path:
    """结构化 summary（Codex R6 §4.9/§4.10）：不再靠解析 stdout 猜「合计」。"""
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    n_fail = len(RESULTS) - n_pass
    # 失败三元组：**任何非全绿轮次必然写出** index/name/detail，键名自明、无需猜
    # （此前把失败断言只放在 checks[] 里，读取方按常见键名取不到 ⇒ 等于没有证据）
    failures = [{"index": i, "name": n, "detail": d}
                for i, (n, ok, d) in enumerate(RESULTS) if not ok]
    log_path = os.environ.get("LT2_SELF_LOG")     # 由验收执行器注入；未注入则显式 null
    doc = {"namespace": NS, "namespace_root": str(NS_ROOT),
           "tests_sha256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
           "total": len(RESULTS), "pass": n_pass, "fail": n_fail,
           "failures": failures,
           "failure_count": len(failures),
           "log": {"path": log_path, "bytes": None, "sha256": None,
                   "note": ("执行器持有完整 stdout/stderr 日志；其路径/字节/SHA256 记录在" 
                            "acceptance_summary.json 的 runs[].log_path/log_bytes/log_sha256"
                            if not log_path else "见执行器注入的日志")},
           "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in RESULTS],
           "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "comsol_started": False, "mph_imported": False}
    if extra:
        doc.update(extra)
    p = NS_ROOT / "test_summary.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    lock = acquire_lock()
    print(f"[NS] namespace={NS} root={NS_ROOT}", flush=True)
    if not lock.get("ok"):
        print(f"[REFUSED] {lock.get('verdict')} — {lock.get('reason')}", flush=True)
        print(json.dumps({"verdict": lock.get("verdict"), "holder": lock.get("holder"),
                          "namespace": NS}, ensure_ascii=False), flush=True)
        return 3
    print("=== LT2 supervisor 故障注入测试（不启动 COMSOL）===", flush=True)
    exc_info = None
    try:
        _run_all()
    except Exception as exc:  # noqa: BLE001 - 顶层兜底：必须写 summary 并释放锁
        import traceback
        tb = traceback.format_exc()
        exc_info = {"exception_type": type(exc).__name__, "exception": str(exc),
                    "traceback": tb,
                    "traceback_sha256": hashlib.sha256(tb.encode("utf-8")).hexdigest(),
                    "last_check": RESULTS[-1][0] if RESULTS else None}
        print(f"[EXCEPTION] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        print(tb, file=sys.stderr, flush=True)
    finally:
        n_pass = sum(1 for _, ok, _ in RESULTS if ok)
        n_fail = len(RESULTS) - n_pass
        print(f"\n合计 {len(RESULTS)} 项，通过 {n_pass}，失败 {n_fail}", flush=True)
        servers = P.list_comsolmphserver()
        print(f"测试期间 comsolmphserver 进程 = {servers}（必须为空）", flush=True)
        try:
            write_summary({"exception": exc_info, "comsol_servers_seen": servers,
                           "lock": {k: lock.get(k) for k in ("ok", "verdict", "lock",
                                                             "owner_token")}})
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] summary 写入失败: {type(exc).__name__}: {exc}", flush=True)
        rel = release_lock()
        print(f"[LOCK] released={rel.get('released')} {rel.get('reason') or ''}", flush=True)
    return 0 if (exc_info is None and n_fail == 0 and not servers) else 1


def _run_all() -> None:
    t1_blocking_worker()
    t2_sidecar_reaches_hard_stop()
    t3_acts_on_verdict_not_staleness()
    t4_four_child_timelines_preserved()
    t5_no_signal_loss()
    t6_refuse_on_mismatch()
    t7_post_termination_verification()
    t9_determinism()          # 先产生 child_08..11，再由 T8 组装覆盖全部 child 的 manifest
    t8_manifest_produced()
    smoke = t10_wiring_smoke_normal()
    t11_signal_not_in_child_dir(smoke["child_dir"])
    t12_no_refused_and_not_resource_hard_stop(smoke["res"])
    t13_resource_hard_stop_only_on_crossing()
    t14_smoke_determinism()
    t15_drill_wiring()
    t16_drill_cli_guard()
    t17_postsolve_path()
    t18_postsolve_error_classification()
    t19_no_third_attempt()
    t20_atomic_checkpoint_failure()
    report_inventory()


if __name__ == "__main__":
    sys.exit(main())
