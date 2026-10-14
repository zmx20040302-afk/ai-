"""可执行的哈希锁（Codex R4 裁定 §7）——冻结快照 + 测试前后校验。

背景：此前我用「读一次、6 秒后再读一次没变」来声明冻结，**不构成冻结机制**
（实测冻结后 13:48–13:49 脚本仍被改动）。本工具改为：

1. `--create`：把被测脚本连同依赖一起复制到 `work/runs/<freeze_id>/snapshot/`，
   写 `freeze_manifest.json`（含 Codex §7 要求的全部字段），并把快照文件设为只读；
2. 之后**从快照目录执行**，不再从持续被修改的 `work/tools` 执行；
3. `--verify`：对当前源文件与 manifest 逐项比对 → 漂移则报告并给非零退出码；
4. `--verify-snapshot`：校验快照自身未被改动。

冻结是 append-only：已存在的 `freeze_id` 永不被覆盖；代码若需修改则新建 freeze_id 并整轮重跑。

用法：
  python work/tools/freeze_snapshot.py --create
  python work/tools/freeze_snapshot.py --verify <freeze_id>
  python work/tools/freeze_snapshot.py --verify-snapshot <freeze_id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
TOOLS = REPO / "work" / "tools"
RUNS = REPO / "work" / "runs"
MODEL = REPO / "work" / "models" / "b_GE_task3_2new_reverse_voltage_drive_v1.mph"
LT1_SUMMARY = REPO / "work" / "runs" / "lt1-reverse-sample" / "lt1_validation_summary_v2.json"

# 被测脚本（快照并逐字节锁定）
TARGETS = ("lt2_production.py", "lt2_sampler.py", "tests_lt2_supervisor.py")
# 依赖件（同样纳入冻结：改它们等于改判据/门禁）
DEPS = ("rt_gate.py",)
# 验收辅助件（实现方建议纳入：验收执行器与静态检查器若不入冻结，验收证据不可第三方复算）
AUX = ("lt2_acceptance_r4.py", "check_undefined_names.py", "lt2_flake_hunt.py",
       "lt2_expected_inventory.json", "lt2_conc_tests.py",
       # rt_gate 的回归套件与 B 的证据文件：不入冻结则该复现与回归不可第三方复算
       "tests_rt_gate.py", "repro_b_sampler.py", "test_atomic_retry.py",
       "min_exec_r8b_evidence.py",
       # T2（父 agent 2026-09-15 裁定）：验收检查器本身必须在冻结集合内。
       # 旧情况：`check_r3_conditions.py` 不在快照 13 个文件里 ⇒ 第三方无法确认
       # "验收时到底用了哪一版检查器"（其产物原先也不含自身 sha256）。
       "check_r3_conditions.py",
       # 同类补齐（父 agent 2026-09-15 T2 的原则）：**冻结器自身**原先也不在冻结集合内
       # ⇒ 改它不会让任何 freeze 失效，而它决定"怎么判定冻结"。冻结器必须自证版本。
       "freeze_snapshot.py")


def aux_present() -> list[Path]:
    return [TOOLS / n for n in AUX if (TOOLS / n).is_file()]


def sha256(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def entry(p: Path, snap_dir: Path | None = None) -> dict:
    e = {"path": str(p), "exists": p.is_file(), "bytes": p.stat().st_size if p.is_file() else None,
         "sha256": sha256(p)}
    if snap_dir is not None:
        s = snap_dir / p.name
        e["snapshot_path"] = str(s)
        e["snapshot_sha256"] = sha256(s)
        e["snapshot_matches"] = (e["sha256"] is not None and e["sha256"] == e["snapshot_sha256"])
    return e


def load_criteria() -> dict:
    """判据哈希只从既有验收文件读取，不自行重算（避免口径漂移）。"""
    try:
        d = json.loads(LT1_SUMMARY.read_text(encoding="utf-8"))
        return {"source": str(LT1_SUMMARY),
                "invariant_criteria_hash": d.get("invariant_criteria_hash"),
                "sweep_spec_hash": d.get("sweep_spec_hash"),
                "artifact_version": d.get("artifact_version")}
    except Exception as exc:  # noqa: BLE001
        return {"source": str(LT1_SUMMARY), "error": f"{type(exc).__name__}: {exc}"}


def cmd_create(args) -> int:
    freeze_id = args.freeze_id or time.strftime("freeze-%Y%m%d-%H%M%S")
    run_dir = RUNS / f"lt2-supervisor-acceptance-{freeze_id}"
    if run_dir.exists():
        print(f"[STOP] freeze 目录已存在，append-only 不得覆盖: {run_dir}")
        return 4
    snap = run_dir / "snapshot"
    snap.mkdir(parents=True)

    files = ([TOOLS / n for n in TARGETS] + [TOOLS / n for n in DEPS] + aux_present())
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        print("[STOP] 被测脚本缺失:", missing)
        return 5
    # ---- 步骤 2：一次读取产生 source inventory（作为冻结窗口的基准）----
    window_start = time.strftime("%Y-%m-%dT%H:%M:%S")
    inventory = {f.name: {"path": str(f), "bytes": f.stat().st_size, "sha256": sha256(f)}
                 for f in files}

    # ---- 步骤 3：立即复制并生成快照 ----
    for f in files:
        shutil.copy2(f, snap / f.name)
    snap_inv = {f.name: {"bytes": (snap / f.name).stat().st_size,
                         "sha256": sha256(snap / f.name)} for f in files}

    # ---- 步骤 4b / 6：窗口结束前回读 source；任一变化即放弃该 freeze_id ----
    window_drift = [{"file": f.name, "at_freeze": inventory[f.name]["sha256"], "now": sha256(f)}
                    for f in files if sha256(f) != inventory[f.name]["sha256"]]

    man = {
        "freeze_id": freeze_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "created_by": "work/tools/freeze_snapshot.py",
        "purpose": "LT2 supervisor 验收与资源确认的被测版本锁定（Codex R4 §7）",
        "execution_policy": "测试与正式运行一律从 snapshot/ 目录执行，不从 work/tools 执行",
        "targets": [entry(TOOLS / n, snap) for n in TARGETS],
        "dependencies": [entry(TOOLS / n, snap) for n in DEPS],
        "acceptance_aux": [entry(p, snap) for p in aux_present()],
        "model": entry(MODEL),
        "criteria_hashes": load_criteria(),
        "python": {"executable": sys.executable, "version": sys.version.split()[0],
                   "platform": platform.platform()},
        "source_inventory": inventory,
        "snapshot_inventory": snap_inv,
        "window": {"start": window_start, "end": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "owner": f"pid-{os.getpid()}"},
        "window_drift": window_drift,
        "rule": ("任一哈希在测试前/后或正式运行前/后发生变化 => 该轮结果标记 "
                 "INVALIDATED_BY_CODE_DRIFT，必须新建 freeze_id 并从 T1 整轮重跑；"
                 "窗口内任一文件变化 => 本 freeze_id 直接放弃（status=ABANDONED_CODE_CHANGED_IN_WINDOW），"
                 "不得靠人工解释继续使用"),
    }
    # ---- 步骤 4a / 6：状态判定（窗口漂移则放弃）----
    man["status"] = ("ABANDONED_CODE_CHANGED_IN_WINDOW" if window_drift else "ACTIVE")

    # ---- 步骤 4：写入 manifest，然后回读校验（UTF-8 + JSON 可解析）----
    man_path = run_dir / "freeze_manifest.json"
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    man_sha = sha256(man_path)
    try:
        json.loads(man_path.read_text(encoding="utf-8"))
        readback = {"manifest_utf8_ok": True, "manifest_json_ok": True}
    except Exception as exc:  # noqa: BLE001
        readback = {"manifest_utf8_ok": False, "manifest_json_ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
    readback["manifest_sha256"] = man_sha
    three_way = {
        "source_ok": not window_drift,
        "snapshot_ok": all(snap_inv[k]["sha256"] == inventory[k]["sha256"] for k in inventory),
        "manifest_ok": bool(readback.get("manifest_utf8_ok")),
    }
    three_way["all_ok"] = all(v for k, v in three_way.items() if k != "all_ok")

    # ---- 步骤 5：manifest 自身 SHA256 + 全过程日志写入本 freeze 的专属 run-id（不可复用）----
    (run_dir / "manifest.sha256").write_text(man_sha + "\n", encoding="utf-8")
    with (run_dir / "freeze_procedure.log").open("w", encoding="utf-8") as fh:
        fh.write(f"freeze_id={freeze_id}\n")
        fh.write(f"window_start={man['window']['start']}\nwindow_end={man['window']['end']}\n")
        fh.write(f"window_owner={man['window']['owner']}\n")
        fh.write(f"manifest_path={man_path}\nmanifest_sha256={man_sha}\n")
        for k, v in inventory.items():
            fh.write(f"source   {k} bytes={v['bytes']} sha256={v['sha256']}\n")
        for k, v in snap_inv.items():
            fh.write(f"snapshot {k} bytes={v['bytes']} sha256={v['sha256']}\n")
        for d in window_drift:
            fh.write(f"WINDOW_DRIFT {d['file']} at_freeze={d['at_freeze']} now={d['now']}\n")
        fh.write(f"three_way={json.dumps(three_way, ensure_ascii=False)}\n")
        fh.write(f"readback={json.dumps(readback, ensure_ascii=False)}\n")
        fh.write(f"status={man['status']}\n")

    ro = []
    for f in snap.iterdir():
        try:
            f.chmod(stat.S_IREAD)
            ro.append(f.name)
        except OSError:
            pass

    print(json.dumps({"freeze_id": freeze_id, "status": man["status"],
                      "run_dir": str(run_dir), "snapshot": str(snap),
                      "manifest_sha256": man_sha, "three_way": three_way,
                      "readback": readback, "window_drift": window_drift,
                      "readonly_set": ro,
                      "inventory": {k: (v["sha256"] or "")[:16] for k, v in inventory.items()}},
                     ensure_ascii=False, indent=2))
    # 窗口内发生变化 => 放弃该 freeze_id（保留现场供审计），调用方必须新建 freeze_id
    return 6 if window_drift else 0


def _manifest(run_dir: Path) -> dict:
    return json.loads((run_dir / "freeze_manifest.json").read_text(encoding="utf-8"))


def _compare(man: dict, mode: str, snap_dir: Path | None = None) -> tuple[list[dict], int, list[dict]]:
    """比对。返回 `(判定用 drift, rc, 源漂移 source_drift)`。

    ⚠️ T1（父 agent 2026-09-15 裁定）：旧实现**无条件**先比对源文件（`e["path"]`），
    于是 `--verify-snapshot` 在"快照完好、只是源文件后来被编辑过"时也给出
    `SNAPSHOT_CORRUPTED` —— 把**源漂移**误报成**快照损坏**，会诱导放弃本来有效的运行。
    现在两种模式各查各的：
      · `mode="source"`   ⇒ 判定 = 源 vs manifest（INVALIDATED_BY_CODE_DRIFT）；
      · `mode="snapshot"`  ⇒ 判定 = **快照** vs manifest（SNAPSHOT_CORRUPTED）；
        源漂移作为**独立字段**如实报告，**不**并入同一 verdict。
        （道理：一次运行的证据有效性由"它执行的那份快照"背书；源文件事后被改不影响已完成的运行，
         只影响"该 freeze_id 能否再用于新运行"。）
    """
    source_drift = []
    for group in ("targets", "dependencies", "acceptance_aux"):
        for e in man.get(group, []):
            p = Path(e["path"])
            cur = sha256(p)
            if cur != e["sha256"]:
                source_drift.append({"group": group, "file": p.name,
                                     "frozen": (e["sha256"] or "")[:16],
                                     "current": (cur or "MISSING")[:16]})
    drift: list[dict] = []
    if mode == "snapshot":
        tracked = set()
        for e in (man.get("targets", []) + man.get("dependencies", [])
                  + man.get("acceptance_aux", [])):
            sp = Path(e.get("snapshot_path", ""))
            if e.get("snapshot_path"):
                tracked.add(Path(e["snapshot_path"]).name)
            cur = sha256(sp) if e.get("snapshot_path") else None
            if cur != e.get("snapshot_sha256"):
                drift.append({"group": "snapshot", "file": sp.name,
                              "frozen": (e.get("snapshot_sha256") or "")[:16],
                              "current": (cur or "MISSING")[:16]})
        # Codex 1423 审阅 §3.5：只比对被跟踪文件的哈希，**不能**证明整个 snapshot 未被破坏
        # （实测曾出现未跟踪的 __pycache__/*.pyc）。故此处额外做精确文件集合校验：
        # 新增文件一律判失败；被跟踪文件缺失也判失败。运行 import 应使用 -B。
        if snap_dir is not None and snap_dir.is_dir():
            present = {p.name for p in snap_dir.iterdir()}
            for extra in sorted(present - tracked):
                drift.append({"group": "snapshot_added_untracked", "file": extra,
                              "frozen": "-", "current": "(untracked)"})
            for missing in sorted(tracked - present):
                drift.append({"group": "snapshot_missing", "file": missing,
                              "frozen": "(tracked)", "current": "MISSING"})
    else:
        drift = source_drift
    return drift, (1 if drift else 0), source_drift


def cmd_verify(args) -> int:
    run_dir = RUNS / f"lt2-supervisor-acceptance-{args.freeze_id}"
    if not (run_dir / "freeze_manifest.json").is_file():
        print(f"[STOP] 找不到 freeze manifest: {run_dir}")
        return 3
    man = _manifest(run_dir)
    drift, rc, source_drift = _compare(man, "source")
    out = {"freeze_id": man["freeze_id"], "mode": "source-vs-manifest",
           "drift": drift, "drift_count": len(drift),
           "verdict": "MATCH" if not drift else "INVALIDATED_BY_CODE_DRIFT",
           "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return rc


def cmd_verify_snapshot(args) -> int:
    run_dir = RUNS / f"lt2-supervisor-acceptance-{args.freeze_id}"
    if not (run_dir / "freeze_manifest.json").is_file():
        print(f"[STOP] 找不到 freeze manifest: {run_dir}")
        return 3
    man = _manifest(run_dir)
    drift, rc, source_drift = _compare(man, "snapshot", snap_dir=run_dir / "snapshot")
    # T1：verdict 只看**快照**；源漂移独立报告（它不影响"本次运行由哪份快照背书"，
    # 只影响"该 freeze_id 能否再用于新运行"）。
    out = {"freeze_id": man["freeze_id"], "mode": "snapshot-vs-manifest",
           "drift": drift, "drift_count": len(drift),
           "verdict": "MATCH" if not drift else "SNAPSHOT_CORRUPTED",
           "source_drift": source_drift, "source_drift_count": len(source_drift),
           "source_drift_note": ("源文件漂移**不**影响本次快照判定：快照是运行实际执行的那份字节。"
                                 "但源漂移 ⇒ 该 freeze_id 不可再用于新运行（见 --verify）。"),
           "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return rc


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="可执行哈希锁：冻结快照 + 前后校验")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--create", action="store_true")
    g.add_argument("--verify", metavar="FREEZE_ID")
    g.add_argument("--verify-snapshot", metavar="FREEZE_ID", dest="verify_snapshot")
    ap.add_argument("--freeze-id", default=None, help="--create 时可指定；默认时间戳")
    args = ap.parse_args(argv)
    if args.create:
        return cmd_create(args)
    if args.verify:
        args.freeze_id = args.verify
        return cmd_verify(args)
    args.freeze_id = args.verify_snapshot
    return cmd_verify_snapshot(args)


if __name__ == "__main__":
    raise SystemExit(main())
