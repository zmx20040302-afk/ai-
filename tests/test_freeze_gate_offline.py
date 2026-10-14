# -*- coding: utf-8 -*-
"""A8 门禁的**离线自测**（pytest 风格；同时保留 `python tests/test_freeze_gate_offline.py` 入口）。

这些测试是安全网的一部分：**门禁本身出错（误放行）比没有门禁更危险**，
所以每一类拦截都必须有"通过 / 不通过 / 无法判定"三种用例，负向用例必须**真的被拦下**。

对应关系（每条都来自实测踩坑或红线）：
* 干净冻结件 ⇒ `passed`；
* **源码漂移** ⇒ failed（实测：L741 缺陷修复后 freeze-03 应被拦）；
* **冻结字节被改** ⇒ failed；
* **精确文件集**多一个/少一个 ⇒ failed（实测：在冻结目录里跑自测留下日志即触发）；
* **空证据集合** ⇒ failed（红线：空集合不得通过）；
* **无法判定**（缺 sidecar、清单未声明三方回读）⇒ `inconclusive` 且 **release_allowed=False**；
* **声明了三方回读却拿不出第三方** ⇒ failed（声称无据 ≠ 通过）；
* 真实冻结件 `freeze-06` ⇒ `passed`。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.freeze_gate import (  # noqa: E402
    MANIFEST_NAME, SIDECAR_NAME, run_gate, sha256_file,
)

REAL_FREEZE = (REPO / "work/runs/phase0-field-holdout-20260915/freezes"
               / "freeze_phase1-executor-20260915-06")


def _get(v: dict, name: str) -> dict:
    return next(c for c in v["checks"] if c["name"] == name)


def make_freeze(root: Path, *, n_snapshot: int = 3, with_sidecar: bool = True,
                three_way: bool = True) -> Path:
    """造一个结构正确的冻结件（内容无关紧要：门禁只核对字节与集合）。"""
    root.mkdir(parents=True, exist_ok=True)
    snap = root / "snapshot"
    snap.mkdir(exist_ok=True)
    src_dir = root / "_src"
    src_dir.mkdir(exist_ok=True)
    src_files = []
    for i in range(2):
        p = src_dir / ("locked_%d.py" % i)
        p.write_text("# locked source %d\n" % i, encoding="utf-8")
        src_files.append(p)
    snap_files = []
    for i in range(n_snapshot):
        p = snap / ("artifact_%d.bin" % i)
        p.write_bytes(("payload-%d" % i).encode())
        snap_files.append(p)
    man = {
        "freeze_id": "test-freeze-1", "created_local": "2026-09-16T00:00:00",
        "run_id": "test-run", "purpose": "A8 门禁自测",
        "source_inventory": [{"path": str(p), "exists": True, "bytes": p.stat().st_size,
                              "sha256": sha256_file(p)} for p in src_files],
        "snapshot_inventory": [{"path": str(p), "exists": True, "bytes": p.stat().st_size,
                                "sha256": sha256_file(p)} for p in snap_files],
        "three_way_readback": True if three_way else None,
        "three_way_match": True if three_way else None,
        "status": "FROZEN",
    }
    (root / MANIFEST_NAME).write_text(json.dumps(man, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    if with_sidecar:
        (root / SIDECAR_NAME).write_text(
            sha256_file(root / MANIFEST_NAME) + "  " + MANIFEST_NAME + "\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# 正向
# ---------------------------------------------------------------------------
def test_clean_freeze_passes(tmp_path: Path) -> None:
    v = run_gate(make_freeze(tmp_path / "clean"))
    assert v["verdict"] == "passed", v["reason"]
    assert v["release_allowed"] is True
    assert v["n_failed"] == 0 and v["n_inconclusive"] == 0
    assert v["n_evidence_files"] >= 5          # 2 源 + 3 快照 + 清单(+sidecar)
    assert v["not_checked"], "必须显式列出未检查项"


def test_real_freeze_06_passes() -> None:
    if not REAL_FREEZE.is_dir():
        pytest.skip("本机没有 freeze-06")
    v = run_gate(REAL_FREEZE)
    assert v["verdict"] == "passed", v["reason"]
    assert v["freeze_id"] == "phase1-executor-20260915-06"


# ---------------------------------------------------------------------------
# 负向：字节 / 集合 / 证据
# ---------------------------------------------------------------------------
def test_source_drift_is_blocked(tmp_path: Path) -> None:
    g = make_freeze(tmp_path / "drift")
    (g / "_src" / "locked_0.py").write_text("# tampered\n", encoding="utf-8")
    v = run_gate(g)
    assert _get(v, "source_inventory_integrity")["passed"] is False
    assert v["verdict"] == "failed" and v["release_allowed"] is False


def test_snapshot_byte_change_is_blocked(tmp_path: Path) -> None:
    g = make_freeze(tmp_path / "tamper")
    (g / "snapshot" / "artifact_1.bin").write_bytes(b"tampered")
    v = run_gate(g)
    assert _get(v, "snapshot_hash_match")["passed"] is False
    assert v["verdict"] == "failed"


def test_extra_file_breaks_exact_file_set(tmp_path: Path) -> None:
    """在冻结目录里多写一个文件（例如跑自测留下日志）⇒ 冻结失效。"""
    g = make_freeze(tmp_path / "extra")
    (g / "snapshot" / "selftest_extra.log").write_text("oops\n", encoding="utf-8")
    v = run_gate(g)
    c = _get(v, "snapshot_exact_file_set")
    assert c["passed"] is False and "selftest_extra.log" in json.dumps(c["detail"])
    assert v["verdict"] == "failed"


def test_missing_file_breaks_exact_file_set(tmp_path: Path) -> None:
    g = make_freeze(tmp_path / "missing")
    (g / "snapshot" / "artifact_2.bin").unlink()
    v = run_gate(g)
    assert _get(v, "snapshot_exact_file_set")["passed"] is False
    assert v["verdict"] == "failed"


def test_empty_evidence_must_fail(tmp_path: Path) -> None:
    """红线：空集合不得通过。"""
    g = make_freeze(tmp_path / "empty")
    man = json.loads((g / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["source_inventory"] = []
    man["snapshot_inventory"] = []
    (g / MANIFEST_NAME).write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    (g / SIDECAR_NAME).write_text(sha256_file(g / MANIFEST_NAME) + "\n", encoding="utf-8")
    v = run_gate(g)
    assert _get(v, "no_empty_evidence")["passed"] is False
    assert v["verdict"] == "failed" and v["release_allowed"] is False


# ---------------------------------------------------------------------------
# 负向：无法判定 ≠ 通过
# ---------------------------------------------------------------------------
def test_inconclusive_never_releases(tmp_path: Path) -> None:
    """既无 sidecar、清单也未声明三方回读 ⇒ 全部无 False、仅存 None ⇒ inconclusive 且不放行。"""
    v = run_gate(make_freeze(tmp_path / "incon", with_sidecar=False, three_way=False))
    assert _get(v, "manifest_self_hash")["passed"] is None
    assert v["verdict"] == "inconclusive"
    assert v["release_allowed"] is False


def test_claimed_three_way_without_third_party_fails(tmp_path: Path) -> None:
    """清单**声明** three_way_match=True 但第三方（sidecar）缺失 ⇒ 声称无据 ⇒ failed。"""
    v = run_gate(make_freeze(tmp_path / "claim", with_sidecar=False, three_way=True))
    assert _get(v, "manifest_self_hash")["passed"] is None
    assert _get(v, "three_way_readback")["passed"] is False
    assert v["verdict"] == "failed"


def test_manifest_tamper_caught_by_sidecar(tmp_path: Path) -> None:
    g = make_freeze(tmp_path / "mantamper")
    man = json.loads((g / MANIFEST_NAME).read_text(encoding="utf-8"))
    man["purpose"] = "偷偷改一下"
    (g / MANIFEST_NAME).write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    v = run_gate(g)
    assert _get(v, "manifest_self_hash")["passed"] is False
    assert v["verdict"] == "failed"


# ---------------------------------------------------------------------------
# 脚本入口（保留，便于无 pytest 环境使用）
# ---------------------------------------------------------------------------
def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="a8gate-"))
    tests = [
        ("干净件 ⇒ passed", test_clean_freeze_passes, (tmp / "t1",)),
        ("真实 freeze-06 ⇒ passed", test_real_freeze_06_passes, ()),
        ("源码漂移被拦", test_source_drift_is_blocked, (tmp / "t2",)),
        ("快照字节被改被拦", test_snapshot_byte_change_is_blocked, (tmp / "t3",)),
        ("文件集多一个被拦", test_extra_file_breaks_exact_file_set, (tmp / "t4",)),
        ("文件集少一个被拦", test_missing_file_breaks_exact_file_set, (tmp / "t5",)),
        ("空证据判失败", test_empty_evidence_must_fail, (tmp / "t6",)),
        ("无法判定不放行", test_inconclusive_never_releases, (tmp / "t7",)),
        ("声称三方回读无第三方 ⇒ failed", test_claimed_three_way_without_third_party_fails,
         (tmp / "t8",)),
        ("清单被改被 sidecar 抓出", test_manifest_tamper_caught_by_sidecar, (tmp / "t9",)),
    ]
    fails = []
    for name, fn, a in tests:
        try:
            fn(*a)
            print("  [PASS] %s" % name)
        except Exception as exc:                      # noqa: BLE001
            print("  [FAIL] %s -- %s: %s" % (name, type(exc).__name__, str(exc)[:120]))
            fails.append(name)
    print("\n%s" % ("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails)))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
