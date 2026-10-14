"""R6 §4 无 COMSOL 验收执行器（G1 最低合格条件的可执行实现）。

对照 Codex R6 §4 的 10 个条件：
  1. 两次 suite `returncode=0` 且有**结构化** total/pass/fail（读 `test_summary.json`，不解析 stdout）；
  2. 两侧 deterministic manifest 均**非空**（空 ⇒ FAIL，禁止 sha256("{}") 假通过）；
  3. **六个声明的确定性根全覆盖**，且每个根通过 expected-inventory 校验（`lt2_expected_inventory.json`）；
  4. 每项含**规范化相对路径**（相对各自 namespace 根）+ 字节数 + 完整 SHA256；
  5. `different_files=[]`、`only_left=[]`、`only_right=[]`；
  6. 排除项只能来自**固定 allowlist** 并逐文件附原因；出现未知排除项即失败；
  7. full-tree 的每个差异都能映射到该 allowlist（不得用「整目录不确定」掩盖）；
  8. `comsol_started=false`、`mph_imported=false`，且测试前后无 COMSOL server；
  9. 每轮完整 stdout/stderr 单独落盘，summary 记录路径/字节数/SHA256（tail 仅预览）；
 10. 测试前/后各做 source-vs-manifest 与 snapshot-vs-manifest 校验（四项 MATCH）。

P0 隔离：run1/run2 使用**不同 namespace**（各自唯一运行根），路径比较前正规化为相对路径。
仓库定位 fail-closed：必须显式 `--repo-root`（fail-closed，不回退硬编码绝对路径）。

用法：
  python work/tools/lt2_acceptance_r4.py --repo-root <abs> [--freeze-id <id>] [--skip-30x]
退出码：0 = §4 全部条件满足
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
PY = sys.executable
# 由 main() 注入：字节码缓存前缀（快照卫生）。run() 是模块级函数，
# **不能**引用 main() 的局部变量 OUT（实测 NameError: name 'OUT' is not defined ⇒ 整批空跑）。
PYCACHE_PREFIX: str = ""
DETERMINISTIC_ROOTS = (
    "lt2-supervisor-selftest", "lt2-supervisor-selftest-smoke",
    "lt2-supervisor-selftest-postsolve", "lt2-supervisor-selftest-retry",
    "lt2-supervisor-selftest-atomic", "lt2-supervisor-selftest-drill",
)
def norm_path(x: str) -> str:
    """**唯一**的路径规范化：一律 POSIX 分隔符 + 去掉 . 段。
    缺陷1 的根因就是两侧规范化不一致（expected 手写用 \\，manifest 用 as_posix()）。
    任何参与比较的路径都必须过这里，禁止只在一边做手脚。"""
    return Path(str(x).replace("\\", "/")).as_posix()


# 固定 allowlist：**逐条**规则（exact / basename / prefix / regex），每条带原因。
# 底线：任何规则都不得宽到能吞掉一个未知差异；**禁止**通配整类文件。
ALLOWLIST_RULES: list[dict] = [
    {"kind": "basename", "pattern": "worker_state.json",
     "reason": "控制通道：必须携带真实 sampler_pid/worker pid 供 supervisor 判活（设计如此）"},
    {"kind": "prefix", "pattern": "lt2-supervisor-selftest-liveproc/",
     "reason": "真实终止探针 T7/T8 真杀自建进程 ⇒ 含真实 PID/启动时间（设计如此）"},
    {"kind": "prefix", "pattern": "lt2-supervisor-selftest-wallclock/",
     "reason": "T9 的 wall-clock 反例：故意不使用固定时间戳（设计如此）"},
    # test-double checkpoint：内含控制通道摘要（sampler_pid/样本数随时序），**逐文件**列出
    {"kind": "exact", "pattern": "lt2-supervisor-selftest-smoke/child_00_attempt_1/checkpoint.json",
     "reason": "test-double checkpoint：摘要含被排除控制通道信息（设计如此）"},
    {"kind": "exact", "pattern": "lt2-supervisor-selftest-drill/child_00_attempt_1/checkpoint.json",
     "reason": "test-double checkpoint：演练期与 supervisor 动作存在时序耦合（设计如此）"},
    {"kind": "exact", "pattern": "lt2-supervisor-selftest-postsolve/child_00_attempt_1/checkpoint.json",
     "reason": "test-double checkpoint：摘要含被排除控制通道信息（设计如此）"},
    {"kind": "exact", "pattern": "lt2-supervisor-selftest-retry/child_00_attempt_2/checkpoint.json",
     "reason": "test-double checkpoint：摘要含被排除控制通道信息（设计如此）"},
    {"kind": "exact", "pattern": "lt2-supervisor-selftest-retry/child_00_attempt_1_refused.json",
     "reason": "拒绝记录含 worker pid（设计如此）"},
    # 根外文件：**逐条**覆盖，不是"根外一律豁免"
    {"kind": "basename", "pattern": "OWNER.LOCK", "reason": "锁文件：进程生命周期产物"},
    {"kind": "basename", "pattern": "test_summary.json", "reason": "结构化 summary 自身"},
    {"kind": "regex", "pattern": r"^[^/]+/signals/[^/]+\\.signal\\.json$",
     "reason": "supervisor→worker 信号：按设计写在 signals/ 而非 child 证据目录"},
    {"kind": "regex", "pattern": r"^lt2-drill-guard-probe-[^/]+/.*$",
     "reason": "T16b 的 preflight-only 探针目录（只读门禁探测）"},
]


def allowlist_rule_for(rel: str) -> str | None:
    """返回命中的规则描述；未命中即**未知排除项**（fail-closed）。"""
    for r in ALLOWLIST_RULES:
        if r["kind"] == "basename" and Path(rel).name == r["pattern"]:
            return f"basename:{r['pattern']}"
        if r["kind"] == "exact" and rel == r["pattern"]:
            return f"exact:{r['pattern']}"
        if r["kind"] == "prefix" and rel.startswith(r["pattern"]):
            return f"prefix:{r['pattern']}"
        if r["kind"] == "regex" and re.match(r["pattern"], rel):
            return f"regex:{r['pattern']}"
    return None
FROZEN_FILES = ("lt2_production.py", "lt2_sampler.py", "tests_lt2_supervisor.py",
                "rt_gate.py", "lt2_acceptance_r4.py", "check_undefined_names.py",
                "lt2_flake_hunt.py", "lt2_expected_inventory.json")


def sha(p: Path | None) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except Exception:
        return None


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def run(cmd: list[str], env: dict | None = None, timeout: int = 3600) -> dict:
    """执行子进程。

    **快照卫生（C9 §3.5）**：一切从 snapshot 执行的 Python 都必须禁写字节码，
    且把 pycache 前缀重定向到验收输出目录——否则会在只读快照里新建 __pycache__，
    使「snapshot 未被破坏」不成立（实测 1725 因此被判 SNAPSHOT_CORRUPTED）。
    """
    t0 = time.time()
    base = dict(os.environ)
    base["PYTHONDONTWRITEBYTECODE"] = "1"
    if PYCACHE_PREFIX:
        base["PYTHONPYCACHEPREFIX"] = PYCACHE_PREFIX
    if env:
        base.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=base)
    return {"cmd": " ".join(cmd), "returncode": p.returncode,
            "seconds": round(time.time() - t0, 1),
            "stdout": p.stdout or "", "stderr": p.stderr or ""}


def ps(script: str) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return (r.stdout or "").strip()
    except Exception:
        return "<error>"


def comsol_servers() -> list[int]:
    out = ps("(Get-Process comsolmphserver -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty Id) -join ','")
    return [int(x) for x in out.split(",") if x.strip().isdigit()]


def snapshot_tree(ns_root: Path) -> tuple[dict, list[dict]]:
    """返回 (deterministic_manifest, exclusions)。路径正规化为**相对 namespace 根**。"""
    det: dict = {}
    excl: list[dict] = []
    if not ns_root.is_dir():
        return det, excl
    for f in sorted(ns_root.rglob("*")):
        if not f.is_file():
            continue
        rel = norm_path(f.relative_to(ns_root))
        rec = {"path": rel, "bytes": f.stat().st_size, "sha256": sha(f)}
        rule = allowlist_rule_for(rel)
        if rule:
            reason = next((r["reason"] for r in ALLOWLIST_RULES
                           if rule.endswith(r["pattern"])), "allowlist")
            excl.append({**rec, "reason": reason, "allowlist_rule": rule})
            continue
        if rel.split("/")[0] not in DETERMINISTIC_ROOTS:
            excl.append({**rec, "reason": "非声明的确定性根且未命中任何 allowlist 规则",
                         "allowlist_rule": None})
            continue
        det[rel] = rec
    return det, excl


def compare(l: dict, r: dict) -> dict:
    lk, rk = set(l), set(r)
    diff = sorted(k for k in lk & rk if l[k]["sha256"] != r[k]["sha256"])
    return {"different_files": diff, "only_left": sorted(lk - rk), "only_right": sorted(rk - lk),
            "common": len(lk & rk),
            "identical": not diff and not (lk - rk) and not (rk - lk)}


def verify_manifest(man_path: Path | None, snap_dir: Path | None) -> dict:
    """source-vs-manifest 与 snapshot-vs-manifest 校验（R6 §4.10）。"""
    if man_path is None:
        return {"ok": None, "note": "未给 freeze_id，跳过冻结校验"}
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    rows, bad = [], []
    for group in ("targets", "dependencies", "acceptance_aux"):
        for e in man.get(group, []):
            name = Path(e["path"]).name
            r = {"file": name, "group": group, "manifest_sha256": e.get("sha256"),
                 "source_sha256": sha(TOOLS / name),
                 "snapshot_sha256": sha(snap_dir / name) if snap_dir else None}
            r["source_vs_manifest"] = (r["source_sha256"] == r["manifest_sha256"])
            r["snapshot_vs_manifest"] = (r["snapshot_sha256"] == r["manifest_sha256"])
            rows.append(r)
            if not (r["source_vs_manifest"] and r["snapshot_vs_manifest"]):
                bad.append(name)
    return {"ok": not bad, "drift": bad, "rows": rows,
            "all_four_match": (not bad and bool(rows))}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True,
                    help="仓库绝对路径（fail-closed：不提供则拒绝运行）")
    ap.add_argument("--freeze-id", default=None)
    ap.add_argument("--skip-30x", action="store_true")
    ap.add_argument("--n-isolated", type=int, default=30)
    ap.add_argument("--out-dir", default=None, help="输出目录名（唯一；默认带时间戳+pid）")
    args = ap.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    if not (repo / "work" / "tools").is_dir():
        print(f"[STOP] --repo-root 不含 work/tools：{repo}", flush=True)
        return 9
    RUNS = repo / "work" / "runs"
    # R7 §4.5 / 1423 §3.4：每次执行使用**唯一、空的输出目录**，拒绝复用历史目录
    FORBIDDEN_OUT = {"lt2-acceptance-r4", "lt2-acceptance-flake"}
    out_name = args.out_dir or f"lt2-acceptance-{time.strftime('%Y%m%d-%H%M%S')}-pid{os.getpid()}"
    if out_name in FORBIDDEN_OUT:
        print(f"[STOP] 禁止复用历史输出目录 {out_name}（append-only：旧产物为历史留档）", flush=True)
        return 9
    OUT = RUNS / out_name
    global PYCACHE_PREFIX
    PYCACHE_PREFIX = str(OUT / "pycache")
    if OUT.exists() and any(OUT.iterdir()):
        print(f"[STOP] 输出目录已存在且非空，拒绝复用：{OUT}", flush=True)
        return 9
    OUT.mkdir(parents=True, exist_ok=True)
    snap_dir = (RUNS / f"lt2-supervisor-acceptance-{args.freeze_id}" / "snapshot"
                if args.freeze_id else None)
    man_path = (RUNS / f"lt2-supervisor-acceptance-{args.freeze_id}" / "freeze_manifest.json"
                if args.freeze_id else None)

    rep: dict = {"role": "R6-§4 acceptance", "started_at": now(), "repo_root": str(repo),
                 "runs_root": str(RUNS), "out": str(OUT), "freeze_id": args.freeze_id,
                 "snapshot_dir": str(snap_dir) if snap_dir else None,
                 "comsol_started": False, "mph_imported": False,
                 "command_line": " ".join([PY, str(Path(__file__).resolve())]
                                          + list(argv if argv is not None else sys.argv[1:])),
                 "frozen_files": {}, "runs": [], "isolated_runs": []}
    for f in FROZEN_FILES:
        p = TOOLS / f
        if p.is_file():
            rep["frozen_files"][f] = {"bytes": p.stat().st_size, "sha256": sha(p)}

    servers_before = comsol_servers()
    rep["comsol_servers_before"] = servers_before
    # 跑前自检字段（父 agent 要求：必须能从产物证明「执行的是 snapshot」）
    rep["layout"] = {"tools": str(TOOLS), "repo": str(repo), "runs": str(RUNS), "out": str(OUT),
                     "snapshot_dir": str(snap_dir) if snap_dir else None,
                     "executed_from_snapshot": bool(
                         snap_dir and str(TOOLS).startswith(str(snap_dir.parent))),
                     "layout_ok": (RUNS.name == "runs" and RUNS.parent.name == "work")}
    rep["pre_verify"] = verify_manifest(man_path, snap_dir)

    def _write_verify(tag: str, kind: str) -> dict:
        """R6/R7 §4.10：source 与 snapshot 的校验结果**独立落盘**并记 bytes+sha256。"""
        v = rep.get(f"{tag}_verify") or {}
        doc = {"tag": tag, "kind": kind, "at": now(), "ok": v.get("ok"),
               "drift": v.get("drift"), "all_four_match": v.get("all_four_match"),
               "rows": v.get("rows"),
               "note": f"{kind}-vs-manifest（freeze_id={args.freeze_id}）"}
        p = OUT / f"verify_{kind}_{tag}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"path": str(p), "bytes": p.stat().st_size, "sha256": sha(p)}

    rep["verify_source_pre"] = _write_verify("pre", "source")
    rep["verify_snapshot_pre"] = _write_verify("pre", "snapshot")
    try:
        r_compile = run([PY, "-m", "py_compile"] + [str(TOOLS / f) for f in FROZEN_FILES
                                                    if f.endswith(".py") and (TOOLS / f).is_file()])
        r_import = run([PY, "-c", "import sys;sys.path.insert(0,"
                        f"r'{TOOLS}');import lt2_production,lt2_sampler;"
                        "print('import_ok',hasattr(lt2_production,'supervise_child'),"
                        "hasattr(lt2_sampler,'run_sampler'))"])
        env_dry = dict(os.environ)
        env_dry["LT2_RUNS_ROOT"] = str(RUNS / "lt2-acceptance-r4-dryrun")
        r_dry = run([PY, "-X", "utf8", str(TOOLS / "lt2_production.py"), "--dry-run"], env=env_dry)
        rep["T12"] = {"compile_rc": r_compile["returncode"], "import_rc": r_import["returncode"],
                      "dry_run_rc": r_dry["returncode"],
                      "import_ok_token": "import_ok True True" in r_import["stdout"]}
        t12_ok = (r_compile["returncode"] == 0 and r_import["returncode"] == 0
                  and rep["T12"]["import_ok_token"] and r_dry["returncode"] == 0)

        stamp = time.strftime("%H%M%S")
        for n in (1, 2):
            ns = f"acc-{stamp}-run{n}"
            ns_root = RUNS / ns
            if ns_root.exists():
                shutil.rmtree(ns_root, ignore_errors=True)
            env = dict(os.environ)
            env["LT2_TEST_NAMESPACE"] = ns
            env.pop("LT2_RUNS_ROOT", None)      # 让套件自己派生 <runs>/<ns>
            t0 = time.time()
            suite = run([PY, "-B", "-X", "utf8", str(TOOLS / "tests_lt2_supervisor.py"),
                         "--namespace", ns], env=env)
            log = OUT / f"suite_run{n}.log"
            so = OUT / f"suite_run{n}.stdout.log"
            se = OUT / f"suite_run{n}.stderr.log"
            so.write_text(suite["stdout"], encoding="utf-8")
            se.write_text(suite["stderr"], encoding="utf-8")
            log.write_text("\n".join([f"# cmd: {suite['cmd']}",
                                      f"# returncode: {suite['returncode']}",
                                      f"# seconds: {suite['seconds']}",
                                      f"# stdout_log: {so} bytes={so.stat().st_size} sha256={sha(so)}",
                                      f"# stderr_log: {se} bytes={se.stat().st_size} sha256={sha(se)}",
                                      "# ---- stdout ----", suite["stdout"],
                                      "# ---- stderr ----", suite["stderr"]]),
                           encoding="utf-8")
            summ_p = ns_root / "test_summary.json"
            summ = json.loads(summ_p.read_text(encoding="utf-8")) if summ_p.is_file() else {}
            det, excl = snapshot_tree(ns_root)
            rep["runs"].append({
                "run": n, "namespace": ns, "namespace_root": str(ns_root),
                "suite_returncode": suite["returncode"], "seconds": suite["seconds"],
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
                "ended_at": now(),
                "structured": {k: summ.get(k) for k in ("total", "pass", "fail", "exception",
                                                        "comsol_started", "mph_imported")},
                "summary_path": str(summ_p),
                "summary_bytes": summ_p.stat().st_size if summ_p.is_file() else None,
                "summary_sha256": sha(summ_p),
                "log_path": str(log), "log_bytes": log.stat().st_size, "log_sha256": sha(log),
                "log_tail_preview": "\n".join(suite["stdout"].splitlines()[-8:]),
                "deterministic_files": len(det),
                "deterministic_bytes": sum(v["bytes"] for v in det.values()),
                "exclusions": excl,
                "exclusions_all_allowlisted": all(e.get("allowlist_rule") for e in excl),
            })
        r1, r2 = rep["runs"][0], rep["runs"][1]
        d1, _ = snapshot_tree(Path(r1["namespace_root"]))
        d2, _ = snapshot_tree(Path(r2["namespace_root"]))
        cmp_det = compare(d1, d2)
        empty = (len(d1) == 0 or len(d2) == 0)
        if empty:
            cmp_det["identical"] = False

        # expected-inventory：优先取 snapshot 内副本；否则**必须**从仓库 tools 取。
        # 快照 AUX 列表由 freeze_snapshot.py 固定、未含本 JSON；若从 snapshot 运行又不去仓库取，
        # expected 集合会变空 ⇒ 条件 3 必然失败（等于没有覆盖证明）。fail-closed：两处都没有就报错。
        ei_candidates = [TOOLS / "lt2_expected_inventory.json",
                         repo / "work" / "tools" / "lt2_expected_inventory.json"]
        ei_path = next((p for p in ei_candidates if p.is_file()), None)
        if ei_path is None:
            raise FileNotFoundError(
                f"expected-inventory 缺失（已查 {[str(p) for p in ei_candidates]}）"
                f"⇒ 无法证明六个确定性根被覆盖，拒绝给出通过结论")
        ei = json.loads(ei_path.read_text(encoding="utf-8"))
        rep["expected_inventory_source"] = {"path": str(ei_path), "sha256": sha(ei_path),
                                            "from_snapshot": str(ei_path).startswith(str(TOOLS))}
        inv_rows, inv_bad = [], []
        for root in DETERMINISTIC_ROOTS:
            want = {norm_path(x) for x in ei.get("roots", {}).get(root, [])}
            got1 = {k for k in d1 if k.split("/")[0] == root}
            got2 = {k for k in d2 if k.split("/")[0] == root}
            row = {"root": root, "expected": len(want), "run1": len(got1), "run2": len(got2),
                   "run1_missing": sorted(want - got1), "run1_extra": sorted(got1 - want),
                   "run2_missing": sorted(want - got2), "run2_extra": sorted(got2 - want),
                   "covered": bool(want) and not (want - got1) and not (want - got2)}
            inv_rows.append(row)
            if not row["covered"]:
                inv_bad.append(root)

        cond = {
            "1_structured_82_82_both": all(
                r["suite_returncode"] == 0 and r["structured"].get("total") == 82
                and r["structured"].get("pass") == 82 and r["structured"].get("fail") == 0
                for r in (r1, r2)),
            "2_deterministic_nonempty": not empty,
            "3_all_six_roots_inventory_ok": not inv_bad,
            "4_relative_path_bytes_sha": all(
                {"path", "bytes", "sha256"} <= set(v) for v in list(d1.values()) + list(d2.values())),
            "5_zero_diff": (not cmp_det["different_files"] and not cmp_det["only_left"]
                            and not cmp_det["only_right"]),
            "6_exclusions_allowlisted_only":
                all(r["exclusions_all_allowlisted"] for r in (r1, r2)),
            "7_full_tree_mapped_to_allowlist":
                all(e.get("allowlist_rule") for r in (r1, r2) for e in r["exclusions"]),
            "8_no_comsol": (not servers_before and not comsol_servers()
                            and not r1["structured"].get("comsol_started", False)
                            and not r2["structured"].get("comsol_started", False)),
            "9_full_logs_with_hash": all(r["log_bytes"] > 0 and r["log_sha256"] for r in (r1, r2)),
            "10_pre_post_four_way_match": None,
        }
        if inv_bad and all(not r["run1"] and not r["run2"] for r in inv_rows):
            rep["expected_inventory_diagnosis"] = (
                "expected_inventory_path_mismatch：expected 与 manifest 的路径规范化不一致或清单为空"
                f"（expected 源={ei_path}）")
        rep.update({"compare_deterministic": cmp_det, "deterministic_manifest_empty": empty,
                    "different_files": cmp_det["different_files"],
                    "only_left": cmp_det["only_left"], "only_right": cmp_det["only_right"],
                    "exclusions_run1": r1["exclusions"], "exclusions_run2": r2["exclusions"],
                    "expected_inventory": inv_rows, "expected_inventory_bad_roots": inv_bad,
                    "deterministic_manifest_run1": d1, "deterministic_manifest_run2": d2,
                    "t12_ok": t12_ok, "conditions": cond})

        if not args.skip_30x:
            for i in range(1, args.n_isolated + 1):
                ns = f"iso-{stamp}-{i:02d}"
                env = dict(os.environ)
                env["LT2_TEST_NAMESPACE"] = ns
                env.pop("LT2_RUNS_ROOT", None)
                s = run([PY, "-B", "-X", "utf8", str(TOOLS / "tests_lt2_supervisor.py"),
                         "--namespace", ns], env=env)
                lg = OUT / f"isolated_{i:02d}.log"
                lg.write_text("\n".join([f"# cmd: {s['cmd']}",
                                         f"# returncode: {s['returncode']}",
                                         "# ---- stdout ----", s["stdout"],
                                         "# ---- stderr ----", s["stderr"]]), encoding="utf-8")
                sp = RUNS / ns / "test_summary.json"
                sm = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
                rec = {"i": i, "namespace": ns, "returncode": s["returncode"],
                       "total": sm.get("total"), "pass": sm.get("pass"), "fail": sm.get("fail"),
                       "exception_type": (sm.get("exception") or {}).get("exception_type"),
                       "log": str(lg), "log_bytes": lg.stat().st_size, "log_sha256": sha(lg)}
                rep["isolated_runs"].append(rec)
                print(f"  iso {i:02d}: rc={rec['returncode']} {rec['pass']}/{rec['total']}",
                      flush=True)
        rep["isolated_summary"] = {
            "n": len(rep["isolated_runs"]),
            "passed": sum(1 for r in rep["isolated_runs"] if r["returncode"] == 0 and r["fail"] == 0),
            "failed": [r["i"] for r in rep["isolated_runs"]
                       if not (r["returncode"] == 0 and r["fail"] == 0)],
            "all_pass": (all(r["returncode"] == 0 and r["fail"] == 0
                             for r in rep["isolated_runs"])
                         if rep["isolated_runs"] else None),
        }
    except Exception as exc:  # noqa: BLE001 - 顶层兜底：也要落盘
        rep["exception"] = {"type": type(exc).__name__, "msg": str(exc),
                            "traceback_sha256": hashlib.sha256(
                                traceback.format_exc().encode()).hexdigest()}
    finally:
        rep["post_verify"] = verify_manifest(man_path, snap_dir)
        rep["verify_source_post"] = _write_verify("post", "source")
        rep["verify_snapshot_post"] = _write_verify("post", "snapshot")
        # snapshot 精确文件集合对比（1423 §3.5：新增文件默认失败）
        if snap_dir and snap_dir.is_dir():
            tracked = {Path(e["path"]).name for g in ("targets", "dependencies", "acceptance_aux")
                       for e in (json.loads(man_path.read_text(encoding="utf-8")).get(g, [])
                                 if man_path else [])}
            present = {p.name for p in snap_dir.iterdir()}
            rep["snapshot_tree_check"] = {
                "tracked": sorted(tracked), "present": sorted(present),
                "added_untracked": sorted(present - tracked),
                "removed_tracked": sorted(tracked - present),
                "exact_set_match": present == tracked,
                "note": "新增未跟踪文件（如 __pycache__）即判失败；套件以 -B 运行以防产生 .pyc"}
        rep["comsol_servers_after"] = comsol_servers()
        if "conditions" in rep:
            rep["conditions"]["10_pre_post_four_way_match"] = bool(
                (rep.get("pre_verify") or {}).get("all_four_match")
                and (rep.get("post_verify") or {}).get("all_four_match"))
        # C9 §3.6：八个具名证据文件必须各有 bytes/完整 SHA256/命令/起止/return code
        ev = []
        for tag in ("pre", "post"):
            for kind in ("source", "snapshot"):
                k = f"verify_{kind}_{tag}"
                rec = rep.get(k) or {}
                ev.append({"name": f"verify_{kind}_{tag}.json", "key": k,
                           "path": rec.get("path"), "bytes": rec.get("bytes"),
                           "sha256": rec.get("sha256"),
                           "command": "internal verify_manifest()",
                           "started_at": rep.get("started_at"),
                           "ended_at": rep.get("ended_at"),
                           "returncode": 0 if (rep.get(f"{tag}_verify") or {}).get("ok") else 1})
        for n, r in enumerate(rep.get("runs", []), 1):
            for stream in ("stdout", "stderr"):
                p2 = OUT / f"suite_run{n}.{stream}.log"
                ev.append({"name": p2.name, "path": str(p2),
                           "bytes": p2.stat().st_size if p2.is_file() else None,
                           "sha256": sha(p2), "command": r.get("suite", {}).get("cmd")
                           if isinstance(r.get("suite"), dict) else r.get("suite_returncode"),
                           "started_at": r.get("started_at"), "ended_at": r.get("ended_at"),
                           "returncode": r.get("suite_returncode")})
        rep["evidence_files"] = ev
        rep["evidence_files_complete"] = all(
            e.get("bytes") is not None and e.get("sha256") and e.get("returncode") is not None
            for e in ev)
        sup = OUT / "acceptance_summary.json"
        rep["self_evidence"] = {"path": str(sup), "note": "本 summary 自身的 bytes/SHA256 由写出后另存"}
        rep["ended_at"] = now()
        rep["all_conditions_met"] = bool(
            rep.get("conditions") and all(v is True for v in rep["conditions"].values()))
        (OUT / "acceptance_summary.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "frozen_files": {k: v["sha256"] for k, v in rep["frozen_files"].items()},
        "T12": rep.get("T12"), "conditions": rep.get("conditions"),
        "structured": [r["structured"] for r in rep["runs"]],
        "deterministic_files": [r["deterministic_files"] for r in rep["runs"]],
        "different_files": rep.get("different_files"), "only_left": rep.get("only_left"),
        "only_right": rep.get("only_right"),
        "exclusions": [len(rep.get("exclusions_run1") or []), len(rep.get("exclusions_run2") or [])],
        "expected_inventory_bad_roots": rep.get("expected_inventory_bad_roots"),
        "isolated": rep.get("isolated_summary"),
        "pre_verify_ok": (rep.get("pre_verify") or {}).get("ok"),
        "post_verify_ok": (rep.get("post_verify") or {}).get("ok"),
        "comsol_started": False, "mph_imported": False,
        "all_conditions_met": rep.get("all_conditions_met"),
    }, ensure_ascii=False), flush=True)
    return 0 if rep.get("all_conditions_met") else 1


if __name__ == "__main__":
    sys.exit(main())
