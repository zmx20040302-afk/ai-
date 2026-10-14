"""最小执行取证器（②③ 修复的「真跑一次」证据，不是静态检查）。

父 agent 流程规则：**修复不得只靠静态检查宣布**——必须先真跑受影响路径，再报哈希、再请冻结。
本脚本就是那次最小执行的取证部分：

  refusals : 用真实 CLI 子进程跑 `--freqs` 的 fail-closed 用例，记录 argv / exit code /
             stdout 中第一条 STOP / 是否创建了 run 目录（跑完对比 work/runs 目录集合）。
  valid    : 直接调用 `parse_freqs()`，对**同一字面量**同时给出旧口径（按逗号切分）与新口径的
             频率条数，证明「空格分隔 ⇒ 旧 1 个 / 新 7 个」这条静默变形已被消除。
  compare  : 从两个 run 的 `batch_manifest.json` 提取本轮新增字段（`freqs_parse`、
             `freeze_evidence`），给出逐字节是否一致的结论（新增字段不得破坏 G3 确定性）。

用法：
  python work/tools/min_exec_r8b_evidence.py refusals --out <json>
  python work/tools/min_exec_r8b_evidence.py valid --out <json>
  python work/tools/min_exec_r8b_evidence.py compare --manifest-a <p1> --manifest-b <p2> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
TOOLS = REPO / "work" / "tools"
RUNS = REPO / "work" / "runs"
PY = str(REPO / "work" / ".venv" / "Scripts" / "python.exe")
TARGET = TOOLS / "lt2_production.py"

SPACE_LITERAL = "5 10 15 20 25 30 35"          # 父 agent 实际发过的那条（旧实现 ⇒ 1 个频率）
COMMA_LITERAL = "5,10,15,20,25,30,35"
REFUSAL_CASES = [
    ("empty_string", [""]),
    ("missing_value", []),          # argparse 自己拒绝（rc=2），登记为「另一层 fail-closed」
    ("whitespace_only", [" "]),
    ("comma_only", [","]),
    ("duplicate_exact", ["5,10,10,20,25,30,35"]),
    ("duplicate_numeric_alias", ["5,5.0,15,20,25,30,35"]),
    ("count_6_not_7", ["5 10 15 20 25 30"]),
    ("invalid_token", ["5,10,abc,20,25,30,35"]),
    ("negative_freq", ["5,10,-15,20,25,30,35"]),
    ("zero_freq", ["5,10,0,20,25,30,35"]),
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_dir_names() -> set[str]:
    return {p.name for p in RUNS.iterdir()} if RUNS.is_dir() else set()


def run_cli(extra: list[str], timeout: int = 120) -> dict:
    argv = [PY, "-B", str(TARGET), *extra]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run(argv, capture_output=True, env=env, timeout=timeout)
    out = r.stdout.decode("utf-8", errors="replace")
    err = r.stderr.decode("utf-8", errors="replace")
    stop = next((ln.strip() for ln in (out + "\n" + err).splitlines() if "[STOP]" in ln), None)
    return {"argv": argv[1:], "exit_code": r.returncode, "stop_line": stop,
            "stdout_sha256": sha256_bytes(r.stdout),
            "stdout_tail": "\n".join(out.splitlines()[-6:]),
            "stderr_tail": "\n".join(err.splitlines()[-4:])}


def mode_refusals(out_p: Path) -> int:
    before = run_dir_names()
    cases = []
    for name, freqs_argv in REFUSAL_CASES:
        argv = ["--run-id", f"should-not-be-created-{name}", "--freqs", *freqs_argv]
        res = run_cli(argv)
        res["case"] = name
        res["expect"] = ("exit=10 (FREQ_PARSE_REFUSAL_EXIT)，且不得创建 run 目录"
                         if name != "missing_value" else
                         "exit=2：argparse 层拒绝「--freqs 没有取值」（另一层 fail-closed）")
        res["ok"] = ((res["exit_code"] == 10 if name != "missing_value" else res["exit_code"] == 2)
                     and f"should-not-be-created-{name}" not in run_dir_names())
        cases.append(res)
    after = run_dir_names()
    rep = {"mode": "refusals", "target": str(TARGET), "target_sha256": sha256_file(TARGET),
           "run_dir_names_before": sorted(before), "run_dir_names_after": sorted(after),
           "new_run_dirs": sorted(after - before), "cases": cases,
           "all_ok": all(c["ok"] for c in cases)}
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": "refusals", "all_ok": rep["all_ok"],
                      "new_run_dirs": rep["new_run_dirs"],
                      "exit_codes": {c["case"]: c["exit_code"] for c in cases}},
                     ensure_ascii=False, indent=2))
    return 0 if rep["all_ok"] else 1


def mode_valid(out_p: Path) -> int:
    sys.path.insert(0, str(TOOLS))
    import lt2_production as P  # noqa: PLC0415

    res = {}
    for label, raw in (("space_separated", SPACE_LITERAL), ("comma_separated", COMMA_LITERAL)):
        tokens, rec = P.parse_freqs(raw)
        res[label] = {
            "raw": raw,
            "old_behaviour_count": len([t for t in str(raw).split(",") if t.strip()]),
            "old_behaviour_note": "旧实现：str.split(\",\") ⇒ 空格分隔只得 1 个",
            "new_tokens": list(tokens),
            "new_count": rec["parsed_freq_list_MHz_count"],
            "parsed_freq_list_MHz": rec["parsed_freq_list_MHz"],
            "expected_count": rec["expected_count"],
            "expected_count_source": rec["expected_count_source"],
            "canonical_plist": rec["canonical_plist"],
            "ok": rec["ok"], "problems": rec["problems"],
        }
    rep = {"mode": "valid", "target_sha256": sha256_file(TARGET),
           "expected_freq_count_constant": P.EXPECTED_FREQ_COUNT,
           "default_freqs": list(P.DEFAULT_FREQS),
           "freq_parse_refusal_exit": P.FREQ_PARSE_REFUSAL_EXIT,
           "freeze_unresolved_exit": P.FREEZE_UNRESOLVED_EXIT,
           "cases": res,
           "all_ok": all(v["ok"] and v["new_count"] == 7 for v in res.values())}
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if rep["all_ok"] else 1


def mode_compare(ma: Path, mb: Path, out_p: Path) -> int:
    def load(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    a, b = load(ma), load(mb)
    keys = ["freqs_parse", "freeze_evidence", "freeze_id", "freeze_hash_pre_post_match",
            "executed_from_frozen_snapshot", "freeze_evidence_complete"]
    per = {}
    for k in keys:
        ja = json.dumps(a.get(k), ensure_ascii=False, sort_keys=True).encode("utf-8")
        jb = json.dumps(b.get(k), ensure_ascii=False, sort_keys=True).encode("utf-8")
        per[k] = {"equal": ja == jb, "sha256_a": sha256_bytes(ja), "sha256_b": sha256_bytes(jb),
                  "bytes_a": len(ja), "bytes_b": len(jb)}
    # 「判定逻辑未变」的机械对照：批次级判定字段必须逐字相同（②③ 只加证据，不改判定）
    beh_keys = ["status", "blocked_reason", "aggregate_pass_conditions", "batch_size",
                "server_lifecycle_size"]
    beh = {}
    for k in beh_keys:
        ja = json.dumps(a.get(k), ensure_ascii=False, sort_keys=True).encode("utf-8")
        jb = json.dumps(b.get(k), ensure_ascii=False, sort_keys=True).encode("utf-8")
        beh[k] = {"equal": ja == jb, "value_a": a.get(k), "value_b": b.get(k)}
    rep = {"mode": "compare",
           "manifest_a": str(ma), "manifest_b": str(mb),
           "manifest_sha256_a": sha256_file(ma), "manifest_sha256_b": sha256_file(mb),
           "manifest_bytes_a": ma.stat().st_size, "manifest_bytes_b": mb.stat().st_size,
           "whole_manifest_equal": ma.read_bytes() == mb.read_bytes(),
           "whole_manifest_equal_note": ("整份 manifest 含 run_id/绝对 child_dir ⇒ 预期不同；"
                                         "本项只用于如实登记"),
           "new_fields": per,
           "new_fields_all_equal": all(v["equal"] for v in per.values()),
           "behaviour_keys": beh,
           "behaviour_equal": all(v["equal"] for v in beh.values()),
           "child_record_new_fields": _child_record(a, b),
           "freeze_hash_pre_post_match_a": a.get("freeze_hash_pre_post_match"),
           "freeze_hash_pre_post_match_b": b.get("freeze_hash_pre_post_match"),
           "executed_from_frozen_snapshot_a": a.get("executed_from_frozen_snapshot"),
           "executed_from_frozen_snapshot_b": b.get("executed_from_frozen_snapshot"),
           "freeze_evidence_complete_a": a.get("freeze_evidence_complete"),
           "freeze_evidence_complete_b": b.get("freeze_evidence_complete"),
           "freeze_evidence_absent_reason_a": a.get("freeze_evidence_absent_reason"),
           "freeze_evidence_absent_reason_b": b.get("freeze_evidence_absent_reason"),
           "freeze_id_a": a.get("freeze_id"), "freeze_id_b": b.get("freeze_id")}
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if (rep["new_fields_all_equal"]
                 and rep["child_record_new_fields"]["equal"]) else 1


def _child_record(a: dict, b: dict) -> dict:
    """child 级新增字段的确定性对照（r8d：正常收尾 / 真实退出码 / enforced_by）。"""

    def pick(m: dict) -> dict:
        ch = (m.get("children") or [{}])[0]
        return {"worker_returncode": ch.get("worker_returncode"),
                "worker_returncode_recorded": ch.get("worker_returncode_recorded"),
                "enforced_by": ch.get("enforced_by"),
                "enforcement_source": ch.get("enforcement_source"),
                "termination_present": ch.get("termination") is not None,
                "normal_completion": ch.get("normal_completion"),
                "retry_class": (ch.get("retry_classification") or {}).get("class")}

    ca, cb = pick(a), pick(b)
    ja = json.dumps(ca, ensure_ascii=False, sort_keys=True).encode("utf-8")
    jb = json.dumps(cb, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"equal": ja == jb, "sha256_a": sha256_bytes(ja), "sha256_b": sha256_bytes(jb),
            "value_a": ca, "value_b": cb}


DECLARED_SCOPE_FUNCS = ("<module>", "parse_freqs", "freeze_dir", "_files_digest", "freeze_verify",
                         "freeze_evidence", "assemble_manifest_from_child_dirs",
                         "classify_enforced_by", "classify_trigger", "classify_retry",
                         "verified_emergency_termination",
                         "finalize_after_solve", "run_combo_worker", "combo_pass_conditions",
                         "all_conditions_true",
                         # 2026-09-15 裁定 A/B/C：T14 确定性化（run_fake_combo_worker + 常量）、
                         # 正常收尾改名（classify_trigger / supervise_child / describe_child_dir /
                         # CHILD_FILE_SPEC）、blocked_reason 与 retry_* 分离（_set_blocked / run_supervisor）
                         "_set_blocked", "describe_child_dir",
                         "run_fake_combo_worker", "supervise_child", "run_supervisor", "main",
                         # preflight 补强（父 agent 2026-09-14 ② 裁定）
                         "classify_comsol_processes", "comsol_process_scan", "preflight")


def _enclosing_defs(new_lines: list[str]) -> list[str]:
    """扫描新文件，给出每个行号所属的顶层 def 名（`<module>` = 模块层/不在任何 def 体内）。

    必须在 def 体结束后回到 `<module>`：否则插在两个 def 之间的**新模块级代码块**
    会被错误归属到上一个 def（实测假阳性：把新块算成改动了 `sha256_file`）。
    """
    owner: list[str] = []
    cur = "<module>"
    for ln in new_lines:
        if ln.startswith("def "):
            cur = ln.split("def ", 1)[1].split("(")[0].strip()
        elif ln.strip() and not ln.startswith((" ", "\t", ")", "]", "}")):
            cur = "<module>"   # 顶格且非续行 ⇒ 已离开上一个 def 体
        owner.append(cur)
    return owner


def mode_diff(snapshot: Path, current: Path, out_p: Path, patch_p: Path,
              label_a: str, label_b: str) -> int:
    """父 agent 的「机械差异基线」规则：改动必须与**上一个冻结快照**逐行对照。

    机械判据（不靠关键词猜测）：把每个 hunk 的改动行映射到**新文件里所属的顶层 def**，
    要求这些 def 全部落在本轮**声明范围**内（② 冻结证据 / ③ --freqs 解析加固所触及的函数）。
    """
    import difflib  # noqa: PLC0415

    a = snapshot.read_text(encoding="utf-8").splitlines(keepends=True)
    b = current.read_text(encoding="utf-8").splitlines(keepends=True)
    d = list(difflib.unified_diff(a, b, fromfile=label_a, tofile=label_b, n=2))
    patch_p.parent.mkdir(parents=True, exist_ok=True)
    patch_p.write_text("".join(d), encoding="utf-8")
    owner = _enclosing_defs([l.rstrip("\n") for l in b])

    adds = [l.rstrip("\n") for l in d if l.startswith("+") and not l.startswith("+++")]
    dels = [l.rstrip("\n") for l in d if l.startswith("-") and not l.startswith("---")]

    # 按 hunk 切分，逐 hunk 判断改动行所属 def（新增行用新文件行号；删除行用其上一处新行号近似）
    hunks, cur_h, new_no = [], None, None
    for l in d:
        if l.startswith("@@"):
            if cur_h:
                hunks.append(cur_h)
            new_no = int(l.split("+")[1].split(",")[0].split(" ")[0])
            cur_h = {"header": l.rstrip("\n"), "new_start": new_no,
                     "enclosing_defs": set(), "added": 0, "deleted": 0,
                     "first_added": None, "first_deleted": None}
            continue
        if cur_h is None:
            continue
        if l.startswith("+") and not l.startswith("+++"):
            cur_h["added"] += 1
            # 纯空白新增行不携带代码，不参与「所属 def」归属（否则 diff 对齐会把
            # 上一个函数的尾部空行算成越界改动——实测假阳性：sha256_file）。
            # 注意：必须先去掉 `+` 标记再判空白，否则 `"+"` 本身非空。
            if l[1:].strip() and new_no is not None and 1 <= new_no <= len(owner):
                cur_h["enclosing_defs"].add(owner[new_no - 1])
            if cur_h["first_added"] is None:
                cur_h["first_added"] = l.rstrip("\n")
            new_no = (new_no or 0) + 1
        elif l.startswith("-") and not l.startswith("---"):
            cur_h["deleted"] += 1
            if cur_h["first_deleted"] is None:
                cur_h["first_deleted"] = l.rstrip("\n")
            if new_no is not None and 1 <= new_no <= len(owner):
                cur_h["enclosing_defs"].add(owner[new_no - 1])
        elif l.startswith(" "):
            if cur_h["first_added"] is not None and cur_h["first_deleted"] is not None:
                pass
            new_no = (new_no or 0) + 1
    if cur_h:
        hunks.append(cur_h)

    touched = sorted({f for h in hunks for f in h["enclosing_defs"]})
    outside = [f for f in touched if f not in DECLARED_SCOPE_FUNCS]
    rep = {"mode": "diff",
           "snapshot": str(snapshot), "current": str(current),
           "snapshot_sha256": sha256_file(snapshot), "snapshot_bytes": snapshot.stat().st_size,
           "current_sha256": sha256_file(current), "current_bytes": current.stat().st_size,
           "patch_path": str(patch_p), "patch_bytes": patch_p.stat().st_size,
           "patch_sha256": sha256_file(patch_p),
           "hunks": [{**h, "enclosing_defs": sorted(h["enclosing_defs"])} for h in hunks],
           "touched_defs": touched,
           "declared_scope_defs": list(DECLARED_SCOPE_FUNCS),
           "touched_defs_outside_declared_scope": outside,
           "deleted_lines": dels,
           "hunk_count": len(hunks), "added_lines": len(adds), "deleted_line_count": len(dels),
           "scope_note": ("声明范围 = ② 冻结证据（freeze_verify / freeze_evidence / run_supervisor / "
                          "run_combo_worker / run_fake_combo_worker / main 的字段与 CLI；"
                          "含裁定 2 的三布尔拆分与裁定 3 的重建件显式声明）"
                          "∪ ③ --freqs 解析加固（parse_freqs / main / supervise_child 的 CLI 传递）"
                          "∪ F1/F2/F3 记录语义（resolve_thresholds / finalize_after_solve / "
                          "combo_pass_conditions / all_conditions_true / run_combo_worker）"
                          "∪ 2026-09-15 裁定 A/B/C：A=正常收尾落记录竞态确定性化"
                          "（run_fake_combo_worker 驻留 + FAKE_CLOSED_LINGER_S 常量）；"
                          "B=正常收尾产物改名 completion_record.json 并明示未发生终止"
                          "（classify_trigger / supervise_child / describe_child_dir 仅注释 / "
                          "CHILD_FILE_SPEC / COMPLETION_FILE_NAME）；"
                          "C=blocked_reason（什么失败了）与 retry_class/retry_reason/"
                          "auto_retry_attempted（为何不重跑）分成两个字段（_set_blocked / run_supervisor）。"
                          "∪ 其所需的 import 与常量。"
                          "`touched_defs_outside_declared_scope` 为空 ⇒ 无越界改动。"),
           }
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if not outside else 1


def mode_smoke(run_id: str, freqs_raw: str, freeze_id: str | None, out_p: Path,
               interval: float = 1.0, combos: str = "[[0.6,4]]") -> int:
    """真跑一次 supervisor（`--worker-role fake-combo-worker`，**不启动 COMSOL**）。

    这是「不是静态检查」的那一半：② 的 `freeze_verify` 前/后核验、`freeze_evidence` 组装、
    `batch_manifest.json` 写入，都在这条路径上被真正执行一次。
    """
    argv = ["--run-id", run_id, "--role", "supervisor", "--worker-role", "fake-combo-worker",
            "--combos", combos, "--max-combos", "1", "--batch-size", "4",
            "--freqs", freqs_raw, "--interval", str(interval), "--gate-poll", "0.3",
            "--fixed-timestamps"]
    if freeze_id:
        argv += ["--freeze-id", freeze_id]
    res = run_cli(argv, timeout=900)
    mp = RUNS / run_id / "batch_manifest.json"
    man: dict = {}
    if mp.is_file():
        try:
            man = json.loads(mp.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            man = {"__unreadable__": f"{type(exc).__name__}: {exc}"}
    rec = {"mode": "smoke", "run_id": run_id, "freeze_id_requested": freeze_id,
           "freqs_raw": freqs_raw, "argv": res["argv"], "exit_code": res["exit_code"],
           "stop_line": res["stop_line"], "stdout_tail": res["stdout_tail"],
           "stdout_sha256": res["stdout_sha256"],
           "manifest_path": str(mp), "manifest_present": mp.is_file(),
           "manifest_bytes": mp.stat().st_size if mp.is_file() else None,
           "manifest_sha256": sha256_file(mp) if mp.is_file() else None,
           "batch_status": man.get("status"), "blocked_reason": man.get("blocked_reason"),
           "aggregate_pass_conditions": man.get("aggregate_pass_conditions"),
           "freqs_parse": man.get("freqs_parse"),
           "freeze_id_in_manifest": man.get("freeze_id"),
           "freeze_hash_pre_post_match": man.get("freeze_hash_pre_post_match"),
           "executed_from_frozen_snapshot": man.get("executed_from_frozen_snapshot"),
           "freeze_evidence_complete": man.get("freeze_evidence_complete"),
           "freeze_evidence": man.get("freeze_evidence"),
           "children": [{"child_index": c.get("child_index"), "attempt": c.get("attempt"),
                         "status": c.get("status"), "checkpoint_present": c.get("checkpoint_present"),
                         # r8d：正常收尾 vs enforce 的可判读字段
                         "worker_returncode": c.get("worker_returncode"),
                         "worker_returncode_recorded": c.get("worker_returncode_recorded"),
                         "enforced_by": c.get("enforced_by"),
                         "enforcement_source": c.get("enforcement_source"),
                         "termination_present": c.get("termination") is not None,
                         "normal_completion_kind": ((c.get("normal_completion") or {})
                                                    .get("trigger_kind")),
                         "normal_completion": c.get("normal_completion"),
                         "retry_class": (c.get("retry_classification") or {}).get("class")}
                        for c in (man.get("children") or [])],
           "signal_files": (sorted(x.name for x in (RUNS / run_id / "signals").iterdir())
                            if (RUNS / run_id / "signals").is_dir() else [])}
    out_p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: rec[k] for k in
                      ("run_id", "freeze_id_requested", "freqs_raw", "exit_code", "stop_line",
                       "manifest_present", "manifest_bytes", "manifest_sha256", "batch_status",
                       "freeze_hash_pre_post_match", "executed_from_frozen_snapshot",
                       "freeze_evidence_complete",
                       "freqs_parse_count", "freeze_verdicts") if k in rec
                      } | {"freqs_parse_count": (rec.get("freqs_parse") or {}).get(
                          "parsed_freq_list_MHz_count"),
                          "freeze_verdicts": {
                              "pre": ((rec.get("freeze_evidence") or {}).get("pre_verdict")),
                              "post": ((rec.get("freeze_evidence") or {}).get("post_verdict")),
                              "pre_post_files_identical":
                                  (rec.get("freeze_evidence") or {}).get(
                                      "pre_post_files_identical"),
                              "definition":
                                  (rec.get("freeze_evidence") or {}).get("definition")}},
                     ensure_ascii=False, indent=2))
    return int(rec["exit_code"])


STANDIN_WORKER_SRC = '''"""r8d「正常完成守卫」测试替身（**只用于确定性复现收尾竞态，绝不是 worker**）。

复现 r3 / r3b 实测的收尾竞态：worker 已写出 checkpoint 并置 stage=closed / stop=true，
但进程**尚未退出**，而 sampler 已由 worker 自己正常停掉。替身置位后故意再活 __HOLD_S__ 秒，
使 supervisor 的轮询必然在该窗口内看到「正常完成」的正面证据。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("LT2_RUNS_ROOT")
            or r"C:\\Users\\zmx\\Desktop\\memsharness\\work\\runs")
argv = sys.argv[1:]


def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


run_id = opt("--run-id")
idx = int(opt("--child-index", "0"))
attempt = int(opt("--attempt", "1"))
child = ROOT / run_id / ("child_%02d_attempt_%d" % (idx, attempt))
child.mkdir(parents=True, exist_ok=True)

# (2) 造一个**已经结束**的进程充当"已正常退出的 sampler"
dead_pid = 2147483
try:
    _p = subprocess.Popen([sys.executable, "-c", "pass"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _p.wait(timeout=30)
    dead_pid = _p.pid
except Exception:
    pass

(child / "worker_state.json").write_text(json.dumps({
    "writer": "standin_worker_r8d", "stage": "closed", "stop": True,
    "cancel_requested": False, "worker_pid": None, "pid": None, "sampler_pid": dead_pid,
    "child_index": idx, "attempt": attempt, "simulated": False,
    "note": "测试替身：worker 已收尾但进程未退出；sampler 已退出"},
    ensure_ascii=False), encoding="utf-8")
(child / "sampler_state.json").write_text(json.dumps({
    "last_sample_ts": time.time(), "sample_index": 5, "verdict": "ok",
    "reasons": [], "warnings": [], "writer": "standin_worker_r8d"},
    ensure_ascii=False), encoding="utf-8")
(child / "checkpoint.json").write_text(json.dumps({
    "status": "pass", "rows": [], "pass_conditions": {"standin": True},
    "note": "测试替身写的最小 checkpoint"}, ensure_ascii=False), encoding="utf-8")
time.sleep(__HOLD_S__)
sys.exit(0)
'''


def _load_probe(source: Path | None):
    """按需从指定 `lt2_production.py`（例如历史冻结快照）载入被测模块——用于**测试灵敏度**证明。"""
    if source is None:
        sys.path.insert(0, str(TOOLS))
        import lt2_production as P  # noqa: PLC0415
        return P
    import importlib.util  # noqa: PLC0415

    sys.path.insert(0, str(Path(source).parent))
    spec = importlib.util.spec_from_file_location("lt2_production_probe", str(source))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lt2_production_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


def mode_guard(run_id: str, out_p: Path, gate_poll: float = 0.2, hold_s: float = 3.0,
               source: Path | None = None, grace_s: float | None = None) -> int:
    """**确定性**验证「正常完成守卫」：不 enforce、不写 signals、记真实 worker 退出码。

    做法：把 `P.SELF` 换成替身脚本（`supervise_child` 用它拼 worker 命令），替身复现收尾竞态
    的**全部条件**（stage=closed + checkpoint + **sampler 已退出** + 有正常样本）后再活 hold_s 秒
    ⇒ 轮询**必然**多轮命中该窗口。
    ⚠️ r3c 教训：第一版替身缺"sampler 已退出"这一条，于是测试通过而真机失败。
    `source` 可指向历史版本，用来证明本测试**有灵敏度**（在旧代码上必然失败）。
    """
    import types  # noqa: PLC0415

    P = _load_probe(Path(source) if source else None)
    runs = P.RUNS
    if grace_s is not None:
        # 有界升级路径的测试：把守卫上界压到很小，使"持续抑制"必然超时 ⇒ 验证会升级、不会永久阻塞
        if hasattr(P, "NORMAL_COMPLETION_GRACE_S"):
            P.NORMAL_COMPLETION_GRACE_S = float(grace_s)

    rd = runs / run_id
    if rd.exists() and any(rd.iterdir()):
        rep = {"mode": "guard", "run_id": run_id, "ok": False,
               "error": "fail-closed：该测试 run 目录已存在且非空（append-only，不得复用）"}
        out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 1

    standin = out_p.parent / "standin_worker_r8d.py"
    # 用占位符替换而不是 str.format：替身源码里含 JSON 花括号
    standin.write_text(STANDIN_WORKER_SRC.replace("__HOLD_S__", repr(float(hold_s))),
                       encoding="utf-8")

    real_self = P.SELF
    P.SELF = standin
    try:
        args = types.SimpleNamespace(
            freqs=("5",), freqs_parse=None, freeze_id=None, interval=1.0, gate_poll=gate_poll,
            worker_role="combo-worker", drill=False, fixed_timestamps=True, allow_retry=True,
            ws_hard_stop_mb=None, commit_hard_stop_mb=None, physical_hard_stop_mb=None)
        res = P.supervise_child(run_id, 0, 0.8, 2, args, attempt=1)
    finally:
        P.SELF = real_self

    child = rd / P.CHILD_DIR_FMT.format(idx=0, attempt=1)
    # 裁定 B（改名）：正常收尾记录现为 `completion_record.json`；历史冻结快照仍写
    # `termination_trigger.json` ⇒ 用 getattr 回退，使**同一套断言**也能在历史快照上跑
    # （三向灵敏度对照必须能跑旧件，才能证明"旧件必失败"）。
    comp_name = getattr(P, "COMPLETION_FILE_NAME", P.TRIGGER_FILE_NAME)
    trig_p = child / comp_name
    trig = json.loads(trig_p.read_text(encoding="utf-8")) if trig_p.is_file() else {}
    sig_p = P.signal_path(run_id, child.name)
    nc = res.get("normal_completion") or {}
    rc = res.get("retry_classification") or {}
    # 历史快照（灵敏度对照用）可能没有该常量 ⇒ 退回字面值，保证同一套断言可跑
    nc_kind = getattr(P, "TRIGGER_KIND_NORMAL_COMPLETION", "normal_completion_sidecar_exit")
    # 守卫记录本身的正确性（两种场景都成立）
    guard_checks = {
        "守卫命中并记为正常收尾": nc.get("trigger_kind") == nc_kind,
        "不是资源硬停（is_hard_stop=false）": nc.get("is_hard_stop") is False,
        "decided 不是 hard_stop_enforce": (nc.get("decided") or {}).get("action")
                                          == "observe_normal_completion",
        "记录含正面证据 markers": bool(nc.get("normal_completion_markers")),
        "守卫记录里 enforced_by 为 null": nc.get("enforced_by") is None,
        "worker_returncode 非 null（① 已修）": res.get("worker_returncode") is not None,
    }
    # 场景 A（默认）：worker 在宽限内自然退出 ⇒ **持续抑制** enforce
    suppress_checks = {
        "enforced_by 为 null（未 enforce）": res.get("enforced_by") is None,
        "没有 termination 记录": res.get("termination") is None,
        "没有 enforcement_source": res.get("enforcement_source") is None,
        "**没有**写 signals 文件": not sig_p.is_file(),
        "worker_returncode 已记录且为 0": res.get("worker_returncode") == 0,
        "重跑分类为 normal_completion": rc.get("class") == "normal_completion",
        "落盘记录 trigger_kind 一致": trig.get("trigger_kind") == nc_kind,
        # 裁定 B：正常收尾**不得**留下名为 termination_trigger.json 的文件
        "落在 completion_record.json 且无 termination_trigger.json":
            trig_p.is_file() and trig_p.name == comp_name
            and not (child / P.TRIGGER_FILE_NAME).is_file()
            and trig.get("termination_performed") is False,
        "文件内明示未发生终止（termination_performed=false）":
            trig.get("termination_performed") is False
            and trig.get("enforcement_requested") is False,
        "多轮轮询后仍持续抑制（非只抑制一次）": (res.get("enforcement_source") is None
                                                and res.get("termination") is None
                                                and not sig_p.is_file()),
        "轮询轮数足以暴露一次性守卫": (hold_s / max(gate_poll, 1e-6)) >= 5,
    }
    # 场景 B（--grace-s 压小上界、替身活得更久）：必须**有界升级**，不得永久阻塞
    timeout_checks = {
        "超时后升级为 enforce（不永久阻塞）": res.get("enforcement_source")
                                              == "normal_completion_timeout",
        "升级标签单一含义（normal_completion_timeout_gate）":
            res.get("enforced_by") == "normal_completion_timeout_gate",
        "升级记录带 enforced_by": trig.get("enforced_by") == "normal_completion_timeout_gate",
        "确实写了 signals（升级=真要求终止）": sig_p.is_file(),
        "升级后仍记真实退出码": res.get("worker_returncode") is not None,
    }
    checks = dict(guard_checks)
    checks.update(timeout_checks if grace_s is not None else suppress_checks)
    polls_possible = hold_s / max(gate_poll, 1e-6)
    rep = {"mode": "guard", "run_id": run_id, "ok": all(checks.values()), "checks": checks,
           "probe_source": str(source) if source else "<work/tools/lt2_production.py>",
           "gate_poll": gate_poll, "hold_s": hold_s, "polls_possible": polls_possible,
           "standin_worker": {"path": str(standin), "sha256": sha256_file(standin)},
           "child_dir": str(child),
           "child_files": sorted(f.name for f in child.iterdir()) if child.is_dir() else [],
           "signal_path": str(sig_p), "signal_present": sig_p.is_file(),
           "worker_returncode": res.get("worker_returncode"),
           "status": res.get("status"), "enforced_by": res.get("enforced_by"),
           "enforcement_source": res.get("enforcement_source"),
           "retry_classification": rc,
           "normal_completion_record": nc,
           "termination_trigger_file": trig}
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": "guard", "probe": rep["probe_source"], "ok": rep["ok"],
                      "failed": [k for k, v in checks.items() if not v],
                      "polls_possible": polls_possible,
                      "worker_returncode": rep["worker_returncode"],
                      "enforcement_source": rep["enforcement_source"],
                      "signal_present": rep["signal_present"],
                      "on_disk_trigger_kind": trig.get("trigger_kind")},
                     ensure_ascii=False, indent=2))
    return 0 if rep["ok"] else 1


def mode_enforced_by(out_p: Path) -> int:
    """`enforced_by` 的单位表：8 个标签各自唯一，且演练优先于资源。"""
    sys.path.insert(0, str(TOOLS))
    import lt2_production as P  # noqa: PLC0415

    cases = [
        ("drill_gate", ("sidecar_health", "threshold_crossed", True),
         "演练阈值越线（drill 优先，绝不能被读成真实资源硬停）"),
        ("resource_gate", ("sidecar_health", "threshold_crossed", False), "真实资源阈值越线"),
        ("integrity_gate", ("sidecar_health", "integrity_failure", False), "完整性失败"),
        ("worker_startup_gate", ("worker_startup_timeout", "worker_startup_failure", False),
         "worker 启动超时"),
        ("worker_requested_gate", ("worker_state.cancel_requested", "unclassified_failure", False),
         "worker 自己 cancel_requested"),
        ("sampler_verdict_gate", ("sampler_state.verdict", "sample_gap_or_health", False),
         "sidecar verdict=hard_stop"),
        ("sidecar_health_gate", ("sidecar_health", "unclassified_failure", False),
         "sidecar 退出/停更（不依赖 verdict）"),
        ("normal_completion_timeout_gate", ("normal_completion_timeout", "unclassified_failure", False),
         "正常收尾已判定但 worker 超时未退出（有界升级）"),
        ("unclassified_gate", ("mystery", "mystery", False), "其余（fail-closed 记录）"),
    ]
    rows = []
    for expect, argv, note in cases:
        got = P.classify_enforced_by(*argv)
        rows.append({"expect": expect, "args": list(argv), "got": got, "note": note,
                     "ok": got == expect})
    all_vals = [P.classify_enforced_by(*c[1]) for c in cases]
    rep = {"mode": "enforced-by", "rows": rows,
           "all_ok": all(r["ok"] for r in rows),
           "values_unique": len(set(all_vals)) == len(all_vals),
           "declared_values": list(P.ENFORCED_BY_VALUES),
           "no_undeclared_value": all(v in P.ENFORCED_BY_VALUES for v in all_vals),
           "definition": P.ENFORCED_BY_DEFINITION}
    rep["ok"] = rep["all_ok"] and rep["values_unique"] and rep["no_undeclared_value"]
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": "enforced-by", "ok": rep["ok"],
                      "map": {r["expect"]: r["got"] for r in rows}}, ensure_ascii=False, indent=2))
    return 0 if rep["ok"] else 1


def _synthetic_timeline(path: Path, ws_values: list[float], hard_stop_rows: int = 0,
                        commit: float = 13000.0, avail: float = 12000.0) -> list[dict]:
    """造一份合成时间线（用于 F1/F2 的最小执行；不含时间戳歧义，全在 solve 阶段）。

    ⚠️ `solve` 阶段的行**必须**带齐全部系统列（`system_available_physical_mb` /
    `commit_available_mb` / `system_memory_load_percent`）：漏一列会让
    `monitoring_ok` 为假 ⇒ 复现"实质条件全绿"的最小执行失效（实测踩坑，
    探针曾漏 `system_memory_load_percent`）。
    """
    rows = []
    pk = max(ws_values) if ws_values else 0.0
    for i, ws in enumerate(ws_values):
        rows.append({"timestamp": f"2026-09-14T04:00:{i:02d}", "current_stage": "solve",
                     "server_working_set_mb": ws,
                     # peak 列必须给：`peak_ws_lt_hard_stop` 读的是 server_peak_ws_mb
                     "server_peak_working_set_mb": pk,
                     "system_available_physical_mb": avail,
                     "system_memory_load_percent": 37,
                     "commit_available_mb": commit,
                     "verdict": ("hard_stop" if i < hard_stop_rows else "ok"),
                     "sample_index": i + 1})
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return rows


def _call_finalize(P, child_dir: Path, th, cancel_rec, jsonl_f: Path, *,
                   drill: bool = False, provenance: dict | None = None,
                   rows: list[dict] | None = None):
    """按生产调用方式驱动 `finalize_after_solve`（不启动 COMSOL）。

    `meta` 的键与 `run_combo_worker` 的传法一致：`drill` 与 `thresholds_provenance` **分别**给，
    不互相覆盖（探针早期版本曾把二者混为一谈，属探针缺陷）。

    `rows`：真实 7 行（`solve_status=ok` + `Vdiff_abs=±2`）可让**全部**布尔条件为真 ⇒
    才能复现「实质条件全绿但状态被判失败」这一缺陷（r3f 实测）；默认 `[]` 会在
    `frequency_rows_7` 上就假，复现不了该缺陷（测试保真度要求）。
    """
    child_dir.mkdir(parents=True, exist_ok=True)
    meta = {"freqs_parse": None, "freeze_id": None, "drill": bool(drill),
            "thresholds_provenance": provenance if provenance is not None else {}}
    return P.finalize_after_solve(
        run_id="f1f2-probe", idx=0, attempt=1, child_dir=child_dir, x=0.8, n1=2,
        freqs=("5",), rows=(rows if rows is not None else []),
        lt2c={"checks": {"pass": True}}, th=th, cancel_rec=cancel_rec,
        set_state=lambda **kw: None, jsonl_f=jsonl_f, clock=lambda: P.FIXED_CLOCK_ISO, meta=meta)


def _rows7_ok() -> list[dict]:
    """7 行全部合格的真实行形状（供"实质条件全绿"的最小执行使用）。"""
    return [{"freq_MHz": str(5 * (i + 1)), "solve_status": "ok",
             "Vdiff_abs": 2.0, "Ptot_W": 1.0} for i in range(7)]


def mode_f1f2(out_p: Path, source: Path | None = None, run_id: str = "lt2-min-exec-f1f2-probe") -> int:
    """F1/F2 的最小执行（(a) 生产路径不变 (b) 演练生效值 (c) F2 正确值 (d) F2 fail-closed）。

    `--source` 指向历史冻结快照 ⇒ 同一套断言必须**失败**（测试灵敏度证明，父 agent 要求保留）。
    """
    import ast  # noqa: PLC0415

    P = _load_probe(Path(source) if source else None)
    runs = P.RUNS
    rd = runs / run_id
    if rd.exists() and any(rd.iterdir()):
        rep = {"mode": "f1f2", "ok": False, "error": f"fail-closed：测试目录已存在且非空：{rd}"}
        out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 1

    results: dict[str, dict] = {}

    def rec(name: str, **obs):
        results[name] = obs

    # ---- (1) F1 调用方（AST）：run_combo_worker 必须 resolve_thresholds(args)，不得裸建 Thresholds()
    tree = ast.parse(Path(P.__file__).read_text(encoding="utf-8"))
    worker = next((n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "run_combo_worker"), None)
    uses_resolve = bare_default = False
    if worker is not None:
        for n in ast.walk(worker):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                fn = getattr(n.value.func, "id", None)
                if fn == "resolve_thresholds":
                    uses_resolve = True
                if fn == "Thresholds":
                    bare_default = True
    rec("F1a_调用方使用生效阈值",
        ok=bool(uses_resolve and not bare_default),
        uses_resolve_thresholds=uses_resolve, bare_default_Thresholds=bare_default)

    # ---- (2) F1 被调方（行为）：生产路径（默认阈值）与演练路径（覆盖 5000）
    class _A:
        def __init__(self, **kw):
            self.drill = kw.get("drill", False)
            self.ws_hard_stop_mb = kw.get("ws_hard_stop_mb")
            self.commit_hard_stop_mb = kw.get("commit_hard_stop_mb")
            self.physical_hard_stop_mb = kw.get("physical_hard_stop_mb")
    prod_th, prod_rec = P.resolve_thresholds(_A(drill=False))
    drill_th, drill_rec = P.resolve_thresholds(_A(drill=True, ws_hard_stop_mb=5000.0))
    ws_prod = [3000.0, 3200.0, 3100.0]
    tl_prod = rd / "probe_prod.jsonl"
    rd.mkdir(parents=True, exist_ok=True)
    _synthetic_timeline(tl_prod, ws_prod)
    ck_prod = _call_finalize(P, rd / "prod", prod_th, None, tl_prod, provenance=prod_rec)
    pc_prod = (ck_prod or {}).get("pass_conditions") or {}
    rec("F1b_生产路径阈值=默认且来源自解释",
        ok=((ck_prod or {}).get("thresholds", {}).get("ws_hard_stop_mb") == 12288.0
            and ((ck_prod or {}).get("thresholds_provenance") or {}).get("drill") is False
            and isinstance((ck_prod or {}).get("thresholds_provenance"), dict)),
        thresholds=(ck_prod or {}).get("thresholds", {}).get("ws_hard_stop_mb"),
        provenance_drill=((ck_prod or {}).get("thresholds_provenance") or {}).get("drill"))
    # 生产路径"数值逐一不变"：三条件按新名存在，且值等价于按默认阈值的直接判断
    peak = max(ws_prod)
    rec("F1c_生产路径三条件按新名存在且取值正确",
        ok=(pc_prod.get("peak_ws_lt_hard_stop") == (peak < 12288.0)
            and pc_prod.get("min_avail_ge_hard_stop") is True
            and pc_prod.get("min_commit_gt_hard_stop") is True
            and "peak_ws_lt_12288" not in pc_prod),
        values={k: pc_prod.get(k) for k in ("peak_ws_lt_hard_stop", "min_avail_ge_hard_stop",
                                            "min_commit_gt_hard_stop")},
        old_names_present=[k for k in pc_prod if k.endswith(("_12288", "_4096"))])

    ws_drill = [5100.0, 5500.0, 5600.0, 5700.0, 5800.0]
    tl_drill = rd / "probe_drill.jsonl"
    _synthetic_timeline(tl_drill, ws_drill)
    ck_drill = _call_finalize(P, rd / "drill", drill_th, None, tl_drill,
                              drill=True, provenance=drill_rec)
    pc_drill = (ck_drill or {}).get("pass_conditions") or {}
    sm_drill = (ck_drill or {}).get("resource_summary") or {}
    rec("F1d_演练路径用生效阈值（5000）并反映到摘要与判定",
        ok=((ck_drill or {}).get("thresholds", {}).get("ws_hard_stop_mb") == 5000.0
            and sm_drill.get("stop_line_event_count") == 5
            and pc_drill.get("peak_ws_lt_hard_stop") is False),
        thresholds=(ck_drill or {}).get("thresholds", {}).get("ws_hard_stop_mb"),
        stop_line_event_count=sm_drill.get("stop_line_event_count"),
        peak_ws_lt_hard_stop=pc_drill.get("peak_ws_lt_hard_stop"),
        provenance_overrides=((ck_drill or {}).get("thresholds_provenance") or {}).get("overrides"))

    # ---- (3) F2 正确值：4 行 hard_stop + cancel_rec ⇒ False + count=4
    tl_hs = rd / "probe_hardstop.jsonl"
    _synthetic_timeline(tl_hs, [3000.0] * 6, hard_stop_rows=4)
    ck_hs = _call_finalize(P, rd / "hardstop", prod_th, {"trigger": {"action": "hard_stop_enforce"}},
                           tl_hs, provenance=prod_rec)
    pc_hs = (ck_hs or {}).get("pass_conditions") or {}
    rec("F2a_取消路径如实统计（False + count=4）",
        ok=(pc_hs.get("no_hard_stop_verdict_samples") is False
            and (ck_hs or {}).get("hard_stop_verdict_sample_count") == 4),
        no_hard_stop_verdict_samples=pc_hs.get("no_hard_stop_verdict_samples"),
        count=(ck_hs or {}).get("hard_stop_verdict_sample_count"))
    # 生产路径（无取消、无 hard_stop 行）⇒ True + count=0
    # ⚠️ r3f 缺陷回归点：**7 行真实合格行** ⇒ 全部布尔条件为真；此时状态必须是 "pass"。
    # 旧代码把计数放进 pass_conditions 并用 `all(pc.values())` 聚合 ⇒ count=0 被读成假 ⇒
    # 全绿却判 fail_or_limited（生产路径实测）。此断言就是该缺陷的复现器。
    ck_ok = _call_finalize(P, rd / "cleanish", prod_th, None, tl_prod,
                           provenance=prod_rec, rows=_rows7_ok())
    pc_ok = (ck_ok or {}).get("pass_conditions") or {}
    rec("F2b_生产路径（0 行 hard_stop）为 True + count=0 且**状态=pass**",
        ok=(pc_ok.get("no_hard_stop_verdict_samples") is True
            and (ck_ok or {}).get("hard_stop_verdict_sample_count") == 0
            and (ck_ok or {}).get("status") == "pass"
            and all(v is True for v in pc_ok.values()) and bool(pc_ok)),
        no_hard_stop_verdict_samples=pc_ok.get("no_hard_stop_verdict_samples"),
        count=(ck_ok or {}).get("hard_stop_verdict_sample_count"),
        status=(ck_ok or {}).get("status"),
        pass_conditions_all_true=all(v is True for v in pc_ok.values()),
        false_keys=[k for k, v in pc_ok.items() if v is not True])
    # F2 计数**不得**出现在 pass_conditions 里（形状不变量；否则真值聚合会再犯同类错误）
    rec("F2d_条件字典只含布尔（计数在顶层，形状违规为空）",
        ok=("hard_stop_verdict_sample_count" not in pc_ok
            and "warning_verdict_sample_count" not in pc_ok
            and (ck_ok or {}).get("pass_condition_shape_violations") == []
            and all(isinstance(v, bool) for v in pc_ok.values())),
        count_in_pass_conditions="hard_stop_verdict_sample_count" in pc_ok,
        shape_violations=(ck_ok or {}).get("pass_condition_shape_violations"),
        non_bool_keys=[k for k, v in pc_ok.items() if not isinstance(v, bool)])
    # ---- (4) F2 fail-closed：时间线不可读 ⇒ False + count=None（**不得为 True**）
    ck_bad = _call_finalize(P, rd / "unreadable", prod_th, None, rd / "does_not_exist.jsonl",
                            provenance=prod_rec)
    pc_bad = (ck_bad or {}).get("pass_conditions") or {}
    rec("F2c_读失败 fail-closed（False + count=None）",
        ok=(pc_bad.get("no_hard_stop_verdict_samples") is False
            and (ck_bad or {}).get("hard_stop_verdict_sample_count") is None),
        no_hard_stop_verdict_samples=pc_bad.get("no_hard_stop_verdict_samples"),
        count=(ck_bad or {}).get("hard_stop_verdict_sample_count"))

    # ---- (4b) 聚合口径本身（纯函数；单一真源 all_conditions_true）
    # 旧代码**没有**这个函数 ⇒ 缺能力即断言失败（fail-closed），不抛异常、不静默跳过
    agg = getattr(P, "all_conditions_true", None)
    if agg is None:
        rec("F4_聚合器：身份比较 + 非空 + 非布尔登记违规",
            ok=False, reason="被测版本没有 all_conditions_true（旧的真值聚合 all(pc.values())）")
    else:
        a_true, v_true = agg({"a": True, "b": True})
        a_defect, v_defect = agg({"a": True, "hard_stop_verdict_sample_count": 0})
        a_empty, v_empty = agg({})
        a_false, v_false = agg({"a": True, "b": False})
        a_int1, v_int1 = agg({"a": 1})
        rec("F4_聚合器：身份比较 + 非空 + 非布尔登记违规",
            ok=((a_true, v_true) == (True, [])
                and a_defect is False and v_defect == ["hard_stop_verdict_sample_count"]
                and a_empty is False and v_empty == []
                and a_false is False and v_false == []
                and a_int1 is False and v_int1 == ["a"]),
            true_case=(a_true, v_true), count0_case=(a_defect, v_defect),
            empty_case=(a_empty, v_empty), false_case=(a_false, v_false),
            int1_case=(a_int1, v_int1))

    # ---- (4c) F5 负向测试：**空时间线必须判失败**（父 agent 2026-09-15 裁定 F5）----
    # 空集旧行为：monitoring_ok=True（`not []`）、peak_ws_lt_hard_stop=True（`or 0`）、
    # commit_hard_stop_samples_0=True（`.get(...,0)`）、no_hard_stop_verdict_samples=True
    # ⇒ "没有任何证据"被当成"没有越线"。本断言在旧代码上**必须失败**（否则是无敏感性测试）。
    tl_empty = rd / "probe_empty.jsonl"
    tl_empty.write_text("", encoding="utf-8")   # keys 齐全但一行样本都没有
    ck_empty = _call_finalize(P, rd / "empty_timeline", prod_th, None, tl_empty,
                              provenance=prod_rec, rows=_rows7_ok())
    pc_empty = (ck_empty or {}).get("pass_conditions") or {}
    vacuous_keys = [k for k in ("monitoring_ok", "peak_ws_lt_hard_stop",
                                "commit_hard_stop_samples_0", "no_hard_stop_verdict_samples")
                    if pc_empty.get(k) is True]
    rec("F5a_空时间线不得判通过（四项空集通过必须为 False）",
        ok=((ck_empty or {}).get("status") != "pass"
            and not vacuous_keys
            and pc_empty.get("monitoring_ok") is False
            and pc_empty.get("peak_ws_lt_hard_stop") is False
            and pc_empty.get("commit_hard_stop_samples_0") is False
            and pc_empty.get("no_hard_stop_verdict_samples") is False
            # 空时间线同样无法证明"没有软线告警" ⇒ 判阻塞（同一原则）
            and (ck_empty or {}).get("blocks_next_combination") is True),
        status=(ck_empty or {}).get("status"), vacuous_keys=vacuous_keys,
        monitoring_ok=pc_empty.get("monitoring_ok"),
        peak_ws_lt_hard_stop=pc_empty.get("peak_ws_lt_hard_stop"),
        commit_hard_stop_samples_0=pc_empty.get("commit_hard_stop_samples_0"),
        no_hard_stop_verdict_samples=pc_empty.get("no_hard_stop_verdict_samples"),
        blocks_next_combination=(ck_empty or {}).get("blocks_next_combination"),
        timeline_rows=((ck_empty or {}).get("resource_summary") or {}).get("timeline_rows"))
    # 对照：非空时间线（同一批 rows）必须仍然 pass ⇒ 修的是"空集漏洞"，不是把正常路径改坏
    ck_nonempty = _call_finalize(P, rd / "nonempty_control", prod_th, None, tl_prod,
                                 provenance=prod_rec, rows=_rows7_ok())
    rec("F5b_非空时间线对照仍为 pass（修复不误伤正常路径）",
        ok=((ck_nonempty or {}).get("status") == "pass"
            and ((ck_nonempty or {}).get("pass_conditions") or {}).get("monitoring_ok") is True),
        status=(ck_nonempty or {}).get("status"),
        monitoring_ok=((ck_nonempty or {}).get("pass_conditions") or {}).get("monitoring_ok"))

    # ---- (5) F3：warning 计数与 blocks_next_combination 必须**始终统计**（取消场景不再恒 False）
    tl_warn = rd / "probe_warning.jsonl"
    _synthetic_timeline(tl_warn, [3000.0] * 5, hard_stop_rows=0)
    fixed = []
    for i, line in enumerate(tl_warn.read_text(encoding="utf-8").splitlines()):
        r = json.loads(line)
        if i < 2:
            r["verdict"] = "warning"
        fixed.append(json.dumps(r, ensure_ascii=False))
    tl_warn.write_text("\n".join(fixed) + "\n", encoding="utf-8")
    ck_warn = _call_finalize(P, rd / "warning_cancelled", prod_th,
                             {"trigger": {"action": "hard_stop_enforce"}}, tl_warn,
                             provenance=prod_rec)
    rec("F3a_取消场景也如实统计 warning（True + count=2）",
        ok=((ck_warn or {}).get("blocks_next_combination") is True
            and (ck_warn or {}).get("warning_verdict_sample_count") == 2),
        blocks_next_combination=(ck_warn or {}).get("blocks_next_combination"),
        count=(ck_warn or {}).get("warning_verdict_sample_count"))
    ck_nowarn = _call_finalize(P, rd / "warning_none", prod_th, None, tl_prod,
                               provenance=prod_rec)
    rec("F3b_无 warning 时不阻塞（False + count=0）",
        ok=((ck_nowarn or {}).get("blocks_next_combination") is False
            and (ck_nowarn or {}).get("warning_verdict_sample_count") == 0),
        blocks_next_combination=(ck_nowarn or {}).get("blocks_next_combination"),
        count=(ck_nowarn or {}).get("warning_verdict_sample_count"))
    ck_wbad = _call_finalize(P, rd / "warning_unreadable", prod_th, None,
                             rd / "does_not_exist.jsonl", provenance=prod_rec)
    rec("F3c_读失败 fail-closed（阻塞 True + count=None）",
        ok=((ck_wbad or {}).get("blocks_next_combination") is True
            and (ck_wbad or {}).get("warning_verdict_sample_count") is None),
        blocks_next_combination=(ck_wbad or {}).get("blocks_next_combination"),
        count=(ck_wbad or {}).get("warning_verdict_sample_count"))

    failed = [k for k, v in results.items() if not v.get("ok")]
    rep = {"mode": "f1f2", "probe_source": str(source) if source else "<work/tools/lt2_production.py>",
           "probe_sha256": sha256_file(Path(P.__file__)), "results": results,
           "failed": failed, "ok": not failed}
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": "f1f2", "probe": rep["probe_source"], "ok": rep["ok"],
                      "failed": failed,
                      "checks": {k: v.get("ok") for k, v in results.items()}},
                     ensure_ascii=False, indent=2))
    return 0 if rep["ok"] else 1


PREFLIGHT_AV_T = 18000.0
PREFLIGHT_CM_T = 21500.0


def mode_preflight(out_p: Path, source: Path | None = None,
                   avail_gate: float = PREFLIGHT_AV_T,
                   commit_gate: float = PREFLIGHT_CM_T) -> int:
    """preflight 补强的最小执行：(1) 纯函数分类（合成清单）(2) 活体结构与门禁默认值
    (3) `gate_pass` 语义未变（== 两次采样判据的合取）。

    `--source` 指向改前快照 ⇒ 同一套断言必须**失败**（灵敏度证明）。
    """
    P = _load_probe(Path(source) if source else None)
    checks: dict[str, bool] = {}
    details: dict[str, object] = {}

    # ---- (1) 纯函数 classify_comsol_processes（合成清单，不依赖真机进程）----
    cls = getattr(P, "classify_comsol_processes", None)
    checks["纯函数 classify_comsol_processes 存在"] = callable(cls)
    if callable(cls):
        syn_blk = [{"pid": 1, "name": "comsolmphserver", "start_iso": "t"},
                   {"pid": 2, "name": "comsolbatch", "start_iso": "t"},
                   {"pid": 3, "name": "comsolcompile", "start_iso": "t"},
                   {"pid": 4, "name": "ComsolUI", "start_iso": "t"},
                   {"pid": 5, "name": "ComsolOtherThing", "start_iso": "t"}]
        r = cls(syn_blk)
        details["synthetic_with_blocking"] = r
        checks["阻断项识别（mphserver/batch/compile）"] = (
            sorted(p["name"] for p in r["blocking_processes"])
            == sorted(["comsolmphserver", "comsolbatch", "comsolcompile"]))
        checks["ComsolUI 不在阻断项里（单列为允许）"] = (
            [p["name"] for p in r["allowed_gui_processes"]] == ["ComsolUI"])
        checks["其它 comsol 名进程如实登记（不隐藏）"] = (
            [p["name"] for p in r["other_comsol_like_processes"]] == ["ComsolOtherThing"])
        checks["有阻断项 ⇒ clean=False"] = r["clean"] is False
        r_gui = cls([{"pid": 4, "name": "ComsolUI", "start_iso": "t"}])
        details["synthetic_gui_only"] = r_gui
        checks["仅 ComsolUI ⇒ clean=True 且被记录（不拒绝启动）"] = (
            r_gui["clean"] is True and r_gui["blocking_count"] == 0
            and [p["name"] for p in r_gui["allowed_gui_processes"]] == ["ComsolUI"])
        r_empty = cls([])
        checks["无 COMSOL 进程 ⇒ clean=True"] = (r_empty["clean"] is True
                                                 and r_empty["blocking_count"] == 0)

    # ---- (2)(3) 活体 preflight：结构 + 门禁默认值 + gate_pass 语义 ----
    try:
        live = P.preflight(avail_gate, commit_gate)     # 位置参数 ⇒ 新旧签名都可调用
    except Exception as exc:  # noqa: BLE001
        live = None
        details["live_error"] = f"{type(exc).__name__}: {exc}"
    checks["preflight 可调用（位置参数兼容）"] = isinstance(live, dict)
    if isinstance(live, dict):
        details["live"] = {k: v for k, v in live.items()
                           if k not in ("comsol_process_scan", "comsol_process_scan_second_sample")}
        checks["门禁默认值 = 18000 / 21500"] = (live.get("gate_defaults") == {
            "physical_avail_gate_mb": PREFLIGHT_AV_T, "commit_gate_mb": PREFLIGHT_CM_T})
        ds = live.get("double_sample") or {}
        checks["双采样记录（两次 + 间隔 + 差值）"] = bool(
            isinstance(ds.get("sample1"), dict) and isinstance(ds.get("sample2"), dict)
            and (ds.get("gap_s") or 0) > 0 and isinstance(ds.get("delta"), dict))
        scan = live.get("comsol_process_scan") or {}
        checks["COMSOL 家族扫描已记录（方法 + 清单 + 阻断名单）"] = bool(
            scan.get("method") and "comsol_family_all" in scan
            and scan.get("blocking_names") == ["comsolmphserver", "comsolbatch", "comsolcompile"])
        checks["扫描覆盖两次采样"] = isinstance(live.get("comsol_process_scan_second_sample"), dict)
        checks["GUI 允许名单被记录"] = bool(scan.get("gui_allowed_names"))
        checks["blocked_by 逐项原因已记录"] = isinstance(live.get("blocked_by"), list)

        def _ok(s: dict, sc: dict) -> bool:
            return bool(s.get("port_free") and sc.get("clean")
                        and s.get("system_available_physical_mb", 0) >= avail_gate
                        and s.get("commit_available_mb", 0) >= commit_gate)

        try:
            exp = _ok(ds["sample1"], scan) and _ok(
                ds["sample2"], live.get("comsol_process_scan_second_sample") or {})
            checks["gate_pass == 两次采样判据的合取（判定语义未变）"] = (live.get("gate_pass") == exp)
            details["gate_pass_recomputed"] = exp
        except Exception as exc:  # noqa: BLE001
            checks["gate_pass == 两次采样判据的合取（判定语义未变）"] = False
            details["gate_pass_recompute_error"] = f"{type(exc).__name__}: {exc}"

    failed = [k for k, v in checks.items() if not v]
    rep = {"mode": "preflight",
           "probe_source": str(source) if source else "<work/tools/lt2_production.py>",
           "probe_sha256": sha256_file(Path(P.__file__)), "checks": checks,
           "failed": failed, "ok": not failed, "details": details}
    out_p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": "preflight", "probe": rep["probe_source"], "ok": rep["ok"],
                      "failed": failed,
                      "live_gate_pass": (details.get("live") or {}).get("gate_pass"),
                      "gate_defaults": (details.get("live") or {}).get("gate_defaults")},
                     ensure_ascii=False, indent=2))
    return 0 if rep["ok"] else 1


def sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["refusals", "valid", "compare", "diff", "smoke",
                                    "guard", "enforced-by", "f1f2", "preflight"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id")
    ap.add_argument("--freqs-raw")
    ap.add_argument("--freeze-id")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--combos", default="[[0.6,4]]")
    ap.add_argument("--gate-poll", type=float, default=0.2)
    ap.add_argument("--hold-s", type=float, default=3.0)
    ap.add_argument("--source", default=None,
                    help="guard 模式的被测件路径（默认 work/tools/lt2_production.py）；"
                         "指向历史冻结快照可用于证明测试灵敏度")
    ap.add_argument("--grace-s", type=float, default=None,
                    help="guard 模式：把 NORMAL_COMPLETION_GRACE_S 压到该值，用于测试有界升级路径")
    ap.add_argument("--manifest-a")
    ap.add_argument("--manifest-b")
    ap.add_argument("--snapshot")
    ap.add_argument("--current")
    ap.add_argument("--patch-out")
    ap.add_argument("--label-a", default="freeze snapshot (previous)")
    ap.add_argument("--label-b", default="current source")
    a = ap.parse_args(argv)
    out_p = Path(a.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    if a.mode == "refusals":
        return mode_refusals(out_p)
    if a.mode == "valid":
        return mode_valid(out_p)
    if a.mode == "diff":
        return mode_diff(Path(a.snapshot), Path(a.current), out_p,
                         Path(a.patch_out), a.label_a, a.label_b)
    if a.mode == "smoke":
        return mode_smoke(a.run_id, a.freqs_raw, a.freeze_id, out_p,
                          interval=a.interval, combos=a.combos)
    if a.mode == "guard":
        return mode_guard(a.run_id, out_p, gate_poll=a.gate_poll, hold_s=a.hold_s,
                          source=Path(a.source) if a.source else None, grace_s=a.grace_s)
    if a.mode == "enforced-by":
        return mode_enforced_by(out_p)
    if a.mode == "f1f2":
        return mode_f1f2(out_p, source=Path(a.source) if a.source else None,
                         run_id=a.run_id or "lt2-min-exec-f1f2-probe")
    if a.mode == "preflight":
        return mode_preflight(out_p, source=Path(a.source) if a.source else None)
    return mode_compare(Path(a.manifest_a), Path(a.manifest_b), out_p)


if __name__ == "__main__":
    raise SystemExit(main())
