# -*- coding: utf-8 -*-
"""S3 门禁完整性测试（任务书 P0-3⑤ 的「自动测试」落点；`INDEX §162`）。

两条线：

* **判据本体**（无外部依赖，永远运行）：`verdict_from_checks` 必须 fail-closed ——
  任一 `False` ⇒ `failed`；无 `False` 但有 `None` ⇒ `inconclusive`；全 `True` ⇒ `passed`；空 ⇒ `inconclusive`。
* **件级审计**（`work/runs/` 下的实测产物；**件缺失即 skip**，以免在干净克隆里假失败）：
  权威门禁件与写回件必须计数自洽、阈值与 `solver_spec.json` 一致、`None` 不得导致 `passed`，
  且写回件的 `supersedes.sha256` 必须等于旧件**现算** sha256（证明旧件未被改动）。
* **阴性对照**：把件里某个 `None` 篡改成 `True` 而不同步计数 ⇒ 审计器**必须**报问题。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.s3_gate_audit import (  # noqa: E402
    S3_THRESHOLD_KEYS, audit_gate_file, audit_supersession, verdict_from_checks,
)

SPEC = REPO / "work" / "runs" / "solver" / "pmut-f1" / "solver_spec.json"
AUTH = REPO / "work" / "runs" / "field-expansion-20261009" / "p2" / "s3_gate_expand.json"
WRITEBACK = REPO / "work" / "runs" / "c-batch-20261010" / "s3_gate_c_batch.json"

needs_artifacts = pytest.mark.skipif(
    not (SPEC.is_file() and AUTH.is_file() and WRITEBACK.is_file()),
    reason="S3 门禁产物不在本机（work/ 不进版本库）⇒ 跳过件级审计，只跑判据本体",
)


def _check(passed, name="c"):
    return {"name": name, "passed": passed}


# --------------------------------------------------------------------------
# 判据本体
# --------------------------------------------------------------------------
def test_all_true_is_passed():
    assert verdict_from_checks([_check(True), _check(True)]) == "passed"


def test_any_false_is_failed_even_with_none():
    assert verdict_from_checks([_check(True), _check(None), _check(False)]) == "failed"


def test_none_without_false_is_inconclusive_not_passed():
    assert verdict_from_checks([_check(True), _check(None)]) == "inconclusive"


def test_empty_is_inconclusive():
    """空集合判 failed 会把「没有证据」错误归因成「证据显示失败」；判 passed 更糟。"""
    assert verdict_from_checks([]) == "inconclusive"


def test_all_none_is_inconclusive():
    assert verdict_from_checks([_check(None), _check(None)]) == "inconclusive"


# --------------------------------------------------------------------------
# 件级审计
# --------------------------------------------------------------------------
@needs_artifacts
def test_authoritative_gate_is_self_consistent_and_reads_spec():
    rep = audit_gate_file(AUTH, SPEC)
    assert rep["ok"], rep["problems"]
    spec = json.loads(SPEC.read_text(encoding="utf-8"))["thresholds"]
    for k in S3_THRESHOLD_KEYS:
        assert rep["provenance_thresholds"][k] == spec[k], k


@needs_artifacts
def test_writeback_gate_has_no_null_and_counts_are_consistent():
    rep = audit_gate_file(WRITEBACK, SPEC)
    assert rep["ok"], rep["problems"]
    assert rep["counts"]["n_inconclusive"] == 0, "写回件不应再有 None（三项已可判定）"
    assert rep["counts"]["n_failed"] == 2, rep["counts"]
    assert rep["verdict_derived"] == "failed"


@needs_artifacts
def test_writeback_declares_old_gate_hash_and_old_gate_is_untouched():
    rep = audit_supersession(WRITEBACK, AUTH)
    assert rep["ok"], rep["problems"]
    assert rep["declared_sha256"] == rep["old_actual_sha256"]


@needs_artifacts
def test_auditor_catches_a_silently_flipped_none(tmp_path):
    """阴性对照：把 None 改成 True 而不同步计数 ⇒ 审计器必须报「计数不自洽」。

    这条是**检验这个检验**：如果审计器抓不到，它给出的 ok 就没有意义。
    """
    doc = json.loads(WRITEBACK.read_text(encoding="utf-8"))
    flipped = 0
    for c in doc["gate"]["checks"]:
        if c.get("passed") is None and flipped == 0:
            c["passed"] = True
            flipped += 1
    if flipped == 0:                      # 写回件里已无 None ⇒ 用另一处篡改做对照
        doc["gate"]["checks"][0]["passed"] = None
        flipped = 1
    tampered = tmp_path / "tampered_gate.json"
    tampered.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    rep = audit_gate_file(tampered, SPEC)
    assert not rep["ok"], "审计器未能抓到被篡改的件（计数/判定不自洽）"
