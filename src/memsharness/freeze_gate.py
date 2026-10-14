# -*- coding: utf-8 -*-
"""A8「验证与冻结」的**确定性门禁层**（fail-closed）。

## 为什么门禁必须是代码（红线）

`release_allowed` / `verdict` 这类判定**不能交给 LLM**：
* 空证据集合必须**判失败**，不能被"看起来没问题"绕过；
* "无法判定"必须**不等于通过**；
* 源码与冻结字节漂移必须**拦停**，不能被解释成"影响不大"。

本模块**复用** `memsharness.consistency` 的 `CheckResult` 与 `evaluate_s3()` 判定语义
（任一 False ⇒ `failed`；任一 None ⇒ `inconclusive` 且不放行；空检查集 ⇒ `inconclusive` 且不放行），
**不另造一套判定**。

## 与现有冻结件的兼容性（已实测）

直接读本仓库既有的冻结目录格式（`freezes/freeze_*/`）：

```
freeze_manifest.json      # 顶层键含 source_inventory / snapshot_inventory / three_way_readback / three_way_match
manifest.sha256           # sidecar：清单自身的哈希（三方回读的第三方）
snapshot/                 # 被冻结的字节
freeze_procedure.log
```

inventory 条目形如 `{"path": <绝对路径>, "exists": bool, "bytes": int, "sha256": str}`。

## 检查项（全部证据化；每项都给出 metric/detail，便于复核）

| 检查 | 通过条件 | 失败/无法判定的处理 |
|---|---|---|
| `manifest_present` | 清单存在且可解析、含 `freeze_id` | 缺失 ⇒ `None`（无法判定） |
| `manifest_self_hash` | sidecar `manifest.sha256` == 清单实际哈希 | sidecar 缺失 ⇒ `None` |
| `source_inventory_integrity` | 每个被锁源文件的现哈希 == 清单记录 | 任一不符 ⇒ False；**空清单 ⇒ False（空集判失败）** |
| `snapshot_hash_match` | `snapshot/` 内每个文件哈希 == 清单记录 | 任一不符 ⇒ False |
| `snapshot_exact_file_set` | `snapshot/` **实际文件集 == 清单记录集**（不多不少） | 多/少任一 ⇒ False |
| `three_way_readback` | 清单记录 / 现算 / sidecar **三方一致** | 缺任一方 ⇒ `None` |
| `no_empty_evidence` | 被哈希的证据条目数 > 0 | =0 ⇒ False（防空集通过） |

`not_checked` 会显式列出**本次没有检查**的项（例如"没有做 COMSOL 复算"），
以免把"没查"读成"查过且通过"。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .consistency import CheckResult, evaluate_s3

GATE_VERSION = "a8-freeze-gate-1"
MANIFEST_NAME = "freeze_manifest.json"
SIDECAR_NAME = "manifest.sha256"
SNAPSHOT_DIRNAME = "snapshot"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _rel(p: Path, root: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def evidence_inventory(root: Path, *, include_snapshot: bool = True) -> list[dict]:
    """冻结目录的**证据清单**（每个文件 bytes + sha256）。这是"三方回读"的第一方。"""
    out = []
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():
            continue
        rel = _rel(p, root)
        if not include_snapshot and rel.startswith(SNAPSHOT_DIRNAME + "/"):
            continue
        out.append({"rel": rel, "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    return out


# ---------------------------------------------------------------------------
# 单项检查
# ---------------------------------------------------------------------------
def check_manifest_present(root: Path) -> tuple[CheckResult, dict]:
    mf = Path(root) / MANIFEST_NAME
    if not mf.is_file():
        return CheckResult("manifest_present", None, None, None,
                           f"缺少 {MANIFEST_NAME}：无法判定任何冻结事实"), {}
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as exc:
        return CheckResult("manifest_present", None, None, None,
                           f"{MANIFEST_NAME} 无法解析：{type(exc).__name__}"), {}
    if not man.get("freeze_id"):
        return CheckResult("manifest_present", False, None, None,
                           "清单缺 freeze_id ⇒ 无法标识被冻结对象"), {"manifest": man}
    return CheckResult("manifest_present", True, None, None, "",
                       {"freeze_id": man.get("freeze_id"),
                        "purpose": man.get("purpose"),
                        "status": man.get("status")}), {"manifest": man}


def check_manifest_self_hash(root: Path, man: dict) -> tuple[CheckResult, dict]:
    side = Path(root) / SIDECAR_NAME
    if not side.is_file():
        return CheckResult("manifest_self_hash", None, None, None,
                           f"缺少 sidecar {SIDECAR_NAME}：清单自身哈希无法独立核对"), {}
    want = side.read_text(encoding="utf-8").strip().split()[0].lower()
    got = sha256_file(Path(root) / MANIFEST_NAME)
    ok = (want == got)
    return CheckResult("manifest_self_hash", ok, 0.0 if ok else 1.0, 0.0,
                       "" if ok else f"清单哈希不符：sidecar={want[:16]} 现算={got[:16]}",
                       {"sidecar": want, "recomputed": got}), {}


def _inventory_of(man: dict, key: str) -> list[dict]:
    inv = man.get(key) or []
    return [e for e in inv if isinstance(e, dict) and e.get("path")]


def check_source_inventory_integrity(man: dict) -> tuple[CheckResult, dict]:
    """被锁**源文件**的现哈希必须等于清单记录；**空清单判失败**（防空集通过）。"""
    inv = _inventory_of(man, "source_inventory")
    if not inv:
        return CheckResult("source_inventory_integrity", False, None, None,
                           "source_inventory 为空 ⇒ 没有任何被锁源文件可核对（按规则判失败）"), {}
    bad, checked = [], 0
    for e in inv:
        p = Path(e["path"])
        if not p.is_file():
            bad.append({"path": e["path"], "why": "文件不存在"})
            continue
        checked += 1
        got = sha256_file(p)
        if got != (e.get("sha256") or "").lower():
            bad.append({"path": e["path"], "why": "哈希不符",
                        "recorded": (e.get("sha256") or "")[:16], "recomputed": got[:16]})
    ok = not bad
    return CheckResult("source_inventory_integrity", ok, float(len(bad)), 0.0,
                       "" if ok else f"{len(bad)}/{len(inv)} 个被锁源文件与清单不符（源码漂移）",
                       {"n_entries": len(inv), "n_checked": checked, "mismatches": bad}), {}


def _snapshot_records(root: Path, man: dict) -> dict[str, dict]:
    out = {}
    for e in _inventory_of(man, "snapshot_inventory"):
        out[_rel(Path(e["path"]), root)] = e
    return out


def check_snapshot_hash_match(root: Path, man: dict) -> tuple[CheckResult, dict]:
    rec = _snapshot_records(root, man)
    if not rec:
        return CheckResult("snapshot_hash_match", False, None, None,
                           "snapshot_inventory 为空 ⇒ 没有可核对的冻结字节（按规则判失败）"), {}
    bad = []
    for rel, e in sorted(rec.items()):
        p = Path(root) / rel
        if not p.is_file():
            bad.append({"rel": rel, "why": "记录在册但文件不存在"})
            continue
        got = sha256_file(p)
        if got != (e.get("sha256") or "").lower():
            bad.append({"rel": rel, "why": "哈希不符",
                        "recorded": (e.get("sha256") or "")[:16], "recomputed": got[:16]})
    ok = not bad
    return CheckResult("snapshot_hash_match", ok, float(len(bad)), 0.0,
                       "" if ok else f"{len(bad)}/{len(rec)} 个冻结文件与清单不符",
                       {"n_entries": len(rec), "mismatches": bad}), {}


def check_snapshot_exact_file_set(root: Path, man: dict) -> tuple[CheckResult, dict]:
    """**精确文件集**：多一个文件也算不通过。

    实测依据：在冻结快照目录里跑一次自测会写出 `selftest_*.log`，
    文件集一变，冻结就不该再被当作"原样"。
    """
    rec = set(_snapshot_records(root, man).keys())
    snap = Path(root) / SNAPSHOT_DIRNAME
    actual = set()
    if snap.is_dir():
        for p in snap.rglob("*"):
            if p.is_file():
                actual.add(_rel(p, Path(root)))
    extra = sorted(actual - rec)
    missing = sorted(rec - actual)
    if not rec and not actual:
        return CheckResult("snapshot_exact_file_set", False, None, None,
                           "快照目录与清单同时为空 ⇒ 没有任何被冻结字节（按规则判失败）"), {}
    ok = (not extra) and (not missing)
    return CheckResult("snapshot_exact_file_set", ok, float(len(extra) + len(missing)), 0.0,
                       "" if ok else f"文件集不一致：多 {len(extra)} 个、少 {len(missing)} 个",
                       {"n_recorded": len(rec), "n_actual": len(actual),
                        "extra": extra[:20], "missing": missing[:20]}), {}


def check_three_way_readback(root: Path, man: dict) -> tuple[CheckResult, dict]:
    """三方回读：清单记录 / 现算 / sidecar（第三方）三者一致才算通过。

    现有冻结件把结果记在 `three_way_readback` / `three_way_match`；若清单里没有这两个键
    （更早的冻结），本项**如实记 `None`（无法判定）**，不猜。
    """
    side = Path(root) / SIDECAR_NAME
    rec = man.get("three_way_readback")
    if rec is None or "three_way_match" not in man:
        return CheckResult("three_way_readback", None, None, None,
                           "清单未记录 three_way_readback/three_way_match ⇒ 无法判定（不等同通过）"), {}
    recomputed = sha256_file(Path(root) / MANIFEST_NAME)
    side_v = side.read_text(encoding="utf-8").strip().split()[0].lower() if side.is_file() else None
    decl = bool(man.get("three_way_match"))
    agree = (side_v == recomputed) if side_v else False
    ok = bool(decl and agree)
    return CheckResult("three_way_readback", ok,
                       0.0 if agree else 1.0, 0.0,
                       "" if ok else ("清单声明 three_way_match=%s，sidecar 与现算%s"
                                      % (man.get("three_way_match"),
                                         "一致" if agree else "不一致/缺失")),
                       {"declared_three_way_match": man.get("three_way_match"),
                        "sidecar": (side_v or "")[:16], "recomputed": recomputed[:16]}), {}


def check_no_empty_evidence(man: dict, inv: Iterable[dict]) -> tuple[CheckResult, dict]:
    n_src = len(_inventory_of(man, "source_inventory"))
    n_snap = len(_inventory_of(man, "snapshot_inventory"))
    n_files = len(list(inv))
    n = n_src + n_snap
    ok = n > 0
    return CheckResult("no_empty_evidence", ok, float(n), 1.0,
                       "" if ok else "证据条目为 0 ⇒ 拒绝给出任何『通过』结论（防空集通过）",
                       {"n_source": n_src, "n_snapshot": n_snap, "n_files_on_disk": n_files}), {}


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def run_gate(target: Path, *, extra_checks: Iterable[CheckResult] = ()) -> dict:
    """对**一个冻结目录**跑门禁，返回带 `release_allowed` 的判定（fail-closed）。

    `extra_checks` 供上层追加项目专用检查（例如数据零填充检测、字段类型守卫）；
    它们与内置检查**同一套判定语义**。
    """
    target = Path(target)
    checks: list[CheckResult] = []
    details: dict[str, Any] = {}

    c, d = check_manifest_present(target)
    checks.append(c)
    man = d.get("manifest") or {}
    if man:
        for fn, args in ((check_manifest_self_hash, (target, man)),
                         (check_source_inventory_integrity, (man,)),
                         (check_snapshot_hash_match, (target, man)),
                         (check_snapshot_exact_file_set, (target, man)),
                         (check_three_way_readback, (target, man))):
            c2, _ = fn(*args)
            checks.append(c2)
    inv = evidence_inventory(target)
    c3, _ = check_no_empty_evidence(man, inv)
    checks.append(c3)
    checks.extend(extra_checks)

    verdict = evaluate_s3(checks)          # 复用同一套硬门禁语义（任一 False ⇒ failed）
    verdict = dict(verdict)
    verdict.update({
        "kind": "verification_verdict",
        "gate_version": GATE_VERSION,
        "target_dir": str(target),
        "freeze_id": man.get("freeze_id"),
        "run_id": man.get("run_id"),
        "evidence_inventory": inv,
        "n_evidence_files": len(inv),
        "not_checked": [
            "未做任何 COMSOL 复算（本门禁只核对字节与证据，不重算物理）",
            "未做物理一致性（S3）——那是独立门禁，须单独跑并在放行裁决里并列",
            "未检查模型状态是否可升为 approved_for_use（红线 §5：只能由人批准）",
        ],
        "semantics": ("fail-closed：任一检查为 False ⇒ verdict=failed；任一为 None（无法判定）"
                      "⇒ verdict=inconclusive 且 release_allowed=False；"
                      "证据集合为空 ⇒ 判 failed。`release_allowed` 仅在全部检查为 True 时为 True。"),
    })
    return verdict


def render_md(v: dict) -> str:
    L = ["# A8 验证与冻结 —— 门禁判定", "",
         "- 目标目录：`%s`" % v["target_dir"],
         "- freeze_id：`%s`；run_id：`%s`" % (v.get("freeze_id"), v.get("run_id")),
         "- 门禁版本：`%s`；证据文件数：%d" % (v["gate_version"], v["n_evidence_files"]), "",
         "| 检查 | 通过 | 指标 | 阈值 | 说明 |", "|---|---|---|---|---|"]
    for c in v["checks"]:
        L.append("| `%s` | %s | %s | %s | %s |" % (
            c["name"], {True: "✅", False: "❌", None: "❔"}[c["passed"]],
            "—" if c["metric"] is None else ("%.4g" % c["metric"]),
            "—" if c["threshold"] is None else ("%.4g" % c["threshold"]),
            (c["reason"] or "")[:90]))
    L += ["", "**verdict = `%s`**｜**release_allowed = `%s`**" % (v["verdict"], v["release_allowed"]),
          "", "- 理由：%s" % v["reason"], "",
          "## 本次**没有**检查的项（不得读成「查过且通过」）", ""]
    for x in v["not_checked"]:
        L.append("- %s" % x)
    L += ["", "## 判定语义", "", "```text", v["semantics"], "```", ""]
    return "\n".join(L) + "\n"
