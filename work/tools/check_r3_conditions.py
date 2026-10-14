"""r3 资源确认通过条件检查器（Codex R4 §7 / R6 §4 口径）。

用途：正常资源确认（如 `lt2-resource-confirm-x080-n02-postpagefile-r3`）跑完后，
**一键**逐条判定通过条件，输出结构化 JSON 与退出码；不再靠人读 stdout 末行猜结论
（此前正是"只留 tail"导致失败断言被截断、无法定位）。

设计原则：
  - **fail-closed**：任何证据缺失 => 该项判 False，并给出 `missing` 原因；
  - **不重算模型**：只读 run 目录产物；
  - 判据值全部来自 Codex 裁定，不得在此放宽。

⚠️ **适用对象限于新布局运行**（supervisor 产生：`child_*/` + `worker_state.json` +
`checkpoint.json` + `resource_timeline.jsonl` + `batch_manifest.json`），即 r3 及其后的资源确认。
**不适用于**旧布局的历史运行（如 `lt2-resource-calibration-x080-n02-v2`、`…-x080-n02`），
它们没有 child 目录与 checkpoint，会被大量判 False——那是格式差异，**不是**那些运行失败的证据。
（实测对照：r3 前身 r2 判 14/21 且失败项与 D-D 崩溃吻合；旧布局的 R0 v2 仅 2/21，属预期。）

用法：
  python work/tools/check_r3_conditions.py --run-id lt2-resource-confirm-x080-n02-postpagefile-r3
  python work/tools/check_r3_conditions.py --run-dir work/runs/<run_id> --json-out <path>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
RUNS = REPO / "work" / "runs"

# Codex 裁定阈值（唯一权威：rt_gate.Thresholds；此处只读引用，不重定义）
WS_HARD_STOP_MB = 12288.0
PHYS_HARD_STOP_MB = 4096.0
COMMIT_HARD_STOP_MB = 4096.0
COMMIT_WARNING_MB = 6144.0
MIN_COMMIT_MB = 6144.0
GAP_LIMIT_S = 15.0
EXPECTED_ROWS = 7
EXPECTED_FREQS = 7


def load_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"__unparsable__": line[:120]})
    return out


def load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_rows(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    try:
        return list(csv.DictReader(p.open(encoding="utf-8-sig")))
    except Exception:
        return []


def find_child(run_dir: Path) -> Path | None:
    kids = sorted(run_dir.glob("child_*_attempt_*"))
    return kids[0] if kids else None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check(run_dir: Path) -> dict:
    res: dict = {"run_id": run_dir.name, "run_dir": str(run_dir), "conditions": {},
                 "evidence": {}, "missing": []}

    def C(name: str, ok: bool | None, detail: str = "") -> None:
        res["conditions"][name] = {"pass": bool(ok) if ok is not None else False,
                                   "detail": detail, "unknown": ok is None}

    child = find_child(run_dir)
    if child is None:
        res["missing"].append("child_*_attempt_* 目录")
        C("child_dir_exists", False, "no child_*_attempt_* dir")
    else:
        C("child_dir_exists", True, child.name)

    man = load_json(run_dir / "batch_manifest.json")
    res["evidence"]["batch_manifest_present"] = bool(man)

    tl = load_jsonl(child / "resource_timeline.jsonl") if child else []
    res["evidence"]["timeline_rows"] = len(tl)

    # ---- 7 行结果 / 7 个唯一频率 ----
    rows = read_rows(child / "rows.csv") if child else []
    ckpt = load_json(child / "checkpoint.json") if child else {}
    row_src = rows or (ckpt.get("rows") if isinstance(ckpt.get("rows"), list) else [])
    res["evidence"]["rows_from"] = ("rows.csv" if rows else
                                    ("checkpoint.rows" if row_src else "none"))
    C("rows_eq_7", len(row_src) == EXPECTED_ROWS, f"{len(row_src)} rows")
    freqs = {str(r.get("freq_MHz")) for r in row_src if r.get("freq_MHz") not in (None, "")}
    C("unique_freqs_eq_7", len(freqs) == EXPECTED_FREQS, f"{len(freqs)} unique: {sorted(freqs)[:8]}")

    # ---- 驱动失配 = 0（|Vdiff| == 2.0）----
    mism = [r for r in row_src
            if num(r.get("Vdiff_abs")) is not None and abs(abs(num(r["Vdiff_abs"])) - 2.0) > 1e-6]
    C("drive_mismatch_0", len(row_src) > 0 and len(mism) == 0, f"{len(mism)} mismatched")

    # ---- solve_error = null ----
    ws = load_json(child / "worker_state.json") if child else {}
    res["evidence"]["solve_seconds"] = ws.get("solve_seconds")
    C("solve_error_is_null", "solve_error" in ws and ws.get("solve_error") is None,
      f"solve_error={ws.get('solve_error')!r}")

    # ---- 资源类：三类硬停采样 = 0；commit 预警采样 = 0；commit 最低 > 6144 ----
    if tl:
        ws_hard = sum(1 for r in tl if (num(r.get("server_working_set_mb")) or 0) >= WS_HARD_STOP_MB)
        ph_hard = sum(1 for r in tl if (num(r.get("system_available_physical_mb")) or 1e9) <= PHYS_HARD_STOP_MB)
        cm_hard = sum(1 for r in tl if (num(r.get("commit_available_mb")) or 1e9) <= COMMIT_HARD_STOP_MB)
        cm_warn = sum(1 for r in tl if (num(r.get("commit_available_mb")) or 1e9) <= COMMIT_WARNING_MB)
        cm = [num(r.get("commit_available_mb")) for r in tl if num(r.get("commit_available_mb")) is not None]
        C("ws_hard_stop_samples_0", ws_hard == 0, f"{ws_hard}")
        C("physical_hard_stop_samples_0", ph_hard == 0, f"{ph_hard}")
        C("commit_hard_stop_samples_0", cm_hard == 0, f"{cm_hard}")
        C("commit_warning_samples_0", cm_warn == 0, f"{cm_warn}（若非 0 须暂停解释，非直接放宽）")
        C("min_commit_gt_6144", bool(cm) and min(cm) > MIN_COMMIT_MB,
          f"min={min(cm) if cm else None}")
        res["evidence"]["commit_min"] = min(cm) if cm else None
        res["evidence"]["commit_max"] = max(cm) if cm else None
        res["evidence"]["ws_max"] = max((num(r.get("server_working_set_mb")) or 0) for r in tl)
        res["evidence"]["physical_min"] = min((num(r.get("system_available_physical_mb")) or 1e9)
                                              for r in tl)
        # 缺列：**只看求解阶段**（startup 阶段 server 未起，WS 为空是正常的；
        # Codex 与 R0 脚本的口径都是 solve_stage_missing_system_columns）
        solve_rows = [r for r in tl if r.get("current_stage") == "solve"]
        missing_cols = [c for c in ("server_working_set_mb", "system_available_physical_mb",
                                    "commit_available_mb")
                        if any(r.get(c) in (None, "") for r in solve_rows)]
        C("missing_system_columns_0",
          bool(solve_rows) and not missing_cols,
          f"solve_rows={len(solve_rows)} missing={missing_cols}")
        # 空档 > 15 s（按 timestamp 解析；不可解析则判 False）
        import datetime as _dt
        gaps, bad_ts = 0, 0
        parsed = []
        for r in tl:
            try:
                parsed.append(_dt.datetime.fromisoformat(str(r["timestamp"])))
            except Exception:
                bad_ts += 1
        if bad_ts == 0 and len(parsed) > 1:
            for a, b in zip(parsed, parsed[1:]):
                if (b - a).total_seconds() > GAP_LIMIT_S:
                    gaps += 1
        C("monitoring_gaps_gt_15s_0", bad_ts == 0 and gaps == 0,
          f"gaps={gaps} unparsable_ts={bad_ts}")
    else:
        for k in ("ws_hard_stop_samples_0", "physical_hard_stop_samples_0",
                  "commit_hard_stop_samples_0", "commit_warning_samples_0",
                  "min_commit_gt_6144", "missing_system_columns_0", "monitoring_gaps_gt_15s_0"):
            C(k, False, "timeline 缺失")
        res["missing"].append("resource_timeline.jsonl")

    # ---- checkpoint 有效 ----
    C("checkpoint_valid", bool(ckpt), "checkpoint.json 存在且可解析" if ckpt else "缺失/不可解析")

    # ---- LT2-C 快速门禁 ----
    # 兼容两种形状（父 agent 的检查器最初只认扁平键，是检查器的缺陷，不是产物的缺陷）：
    #   嵌套: lt2c_quick_gate["checks"]["pass"]   ← 生产件的真实形状（更丰富）
    #   扁平: lt2c_quick_gate["pass"]
    # 两者都没有 => fail-closed 判 False（不得因为"读不到"就当通过）。
    lt2c = ckpt.get("lt2c_quick_gate") if isinstance(ckpt, dict) else None
    res["evidence"]["lt2c_quick_gate"] = lt2c
    lt2c_pass = None
    lt2c_shape = "absent"
    if isinstance(lt2c, dict):
        if isinstance(lt2c.get("checks"), dict) and "pass" in lt2c["checks"]:
            lt2c_pass = lt2c["checks"].get("pass")
            lt2c_shape = "nested:checks.pass"
        elif "pass" in lt2c:
            lt2c_pass = lt2c.get("pass")
            lt2c_shape = "flat:pass"
    C("lt2c_quick_gate_pass", lt2c_pass is True, f"shape={lt2c_shape} value={lt2c_pass!r}")

    # ---- 身份证据链 ----
    ident = ws.get("server_identity") if isinstance(ws, dict) else None
    res["evidence"]["server_identity"] = ident
    res["evidence"]["pid_source"] = ws.get("pid_source")
    C("pid_source_is_port_owner", ws.get("pid_source") == "port_owner", f"{ws.get('pid_source')}")
    C("identity_complete",
      bool(ident) and all(ident.get(k) is not None
                          for k in ("pid", "start_filetime", "parent_pid", "parent_is_worker")),
      f"keys={sorted(ident) if isinstance(ident, dict) else None}")

    # ---- 清理 / 端口 ----
    C("port_closed_within_30s", ws.get("port_closed_within_30s") is True,
      f"{ws.get('port_closed_within_30s')}")
    C("server_process_absent",
      bool(ws.get("stop")) and ws.get("stage") == "closed",
      f"stop={ws.get('stop')} stage={ws.get('stage')}")

    # ---- 批次级 ----
    agg = man.get("aggregate_pass_conditions") if isinstance(man, dict) else None
    res["evidence"]["aggregate_pass_conditions"] = agg
    C("no_blocked_reason", man.get("blocked_reason") in (None, ""), f"{man.get('blocked_reason')!r}")

    # ---- 判定容器形状 + child 自身状态（父 agent 2026-09-15 指定：本检查器原先只看
    # 批次级 blocked_reason，**看不到 child 判定本身**，所以 r3f 那种"全绿却 fail_or_limited"
    # 只能靠批次级兜住；非布尔值混进 pass_conditions 更是完全没被检查）----
    pc_ck = ckpt.get("pass_conditions") if isinstance(ckpt, dict) else None
    if isinstance(pc_ck, dict):
        nonbool = sorted(k for k, v in pc_ck.items() if not isinstance(v, bool))
    else:
        nonbool = []
    C("pass_conditions_all_bool",
      isinstance(pc_ck, dict) and bool(pc_ck) and not nonbool,
      f"非布尔字段={nonbool or '无'}；条数={len(pc_ck) if isinstance(pc_ck, dict) else 'n/a'}")
    man_child_status = None
    if isinstance(man, dict):
        chs = man.get("children") or []
        if chs and isinstance(chs[0], dict):
            man_child_status = chs[0].get("status")
    C("child_status_pass",
      man_child_status == "pass" and (ckpt.get("status") == "pass"),
      f"batch_manifest.children[0].status={man_child_status!r}, "
      f"checkpoint.status={ckpt.get('status')!r}")
    # ---- 冻结证据（三个**单义**布尔，见 Codex/父 agent 裁定 2）----
    # 只查其中一个是有洞的：哈希对得上 ≠ 跑的是冻结副本。三者都要（fail-closed）。
    fh = man.get("freeze_hash_pre_post_match")
    ef = man.get("executed_from_frozen_snapshot")
    fe = man.get("freeze_evidence_complete")
    res["evidence"]["freeze_evidence"] = {
        "freeze_hash_pre_post_match": fh,
        "executed_from_frozen_snapshot": ef,
        "freeze_evidence_complete": fe,
        "absent_reason": man.get("freeze_evidence_absent_reason"),
        "freeze_id": man.get("freeze_id"),
    }
    C("freeze_hashes_pre_post_match", fh is True, f"artifact key freeze_hash_pre_post_match={fh!r}")
    C("executed_from_frozen_snapshot", ef is True, f"{ef!r}（防从非冻结副本执行）")
    C("freeze_evidence_complete", fe is True,
      f"{fe!r} reason={man.get('freeze_evidence_absent_reason')!r}")

    # ---- 不得出现 drill 标记（本次是正常确认，非演练）----
    drill_any = any(r.get("drill") for r in tl) or bool(ws.get("drill")) or bool(ckpt.get("drill"))
    C("not_a_drill_run", not drill_any, f"drill_flag_seen={drill_any}")

    passed = [k for k, v in res["conditions"].items() if v["pass"]]
    failed = [k for k, v in res["conditions"].items() if not v["pass"]]
    res["summary"] = {"total": len(res["conditions"]), "passed": len(passed),
                      "failed": len(failed), "failed_names": failed,
                      "all_pass": not failed}
    return res


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="r3 资源确认通过条件检查器（fail-closed）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-id")
    g.add_argument("--run-dir")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir) if args.run_dir else (RUNS / args.run_id)
    if not run_dir.is_dir():
        print(json.dumps({"error": f"run 目录不存在: {run_dir}", "all_pass": False},
                         ensure_ascii=False, indent=2))
        return 3
    out = check(run_dir)
    # ---- T2（父 agent 2026-09-15 裁定）：产物必须**自证**用的是哪一版检查器、以什么参数跑、
    # 以及检查器自身怎么退出的。否则第三方拿到证据也无法确认验收口径。----
    try:
        checker_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        checker_sha = None
    rc = 0 if out["summary"]["all_pass"] else 1
    out["checker_sha256"] = checker_sha
    out["checker_path"] = str(Path(__file__).resolve())
    out["checker_argv"] = list(sys.argv)
    # 写入之后**只剩一次 print**，没有可失败步骤 ⇒ 该字段与真实退出码一致
    out["checker_exited"] = rc
    txt = json.dumps(out, ensure_ascii=False, indent=2)
    print(txt)
    if args.json_out:
        Path(args.json_out).write_text(txt, encoding="utf-8")
    print(f"\n[结论] {out['summary']['passed']}/{out['summary']['total']} 通过；"
          f"all_pass={out['summary']['all_pass']}；失败项={out['summary']['failed_names']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
