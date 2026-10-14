# -*- coding: utf-8 -*-
"""S3 门禁的**只读审计器**（T0.5 / 任务书 P0-3⑤ 的「自动测试」落点）。

为什么需要它：S3 是硬门禁（§6.4 第一跳），它的判定必须满足三条：
  1. **阈值来自 spec**，不得脚本硬编码（门禁件自报 `thresholds_provenance.modified = false`）；
  2. **`None` 不得算通过**：任一 `passed is None` ⇒ 该门禁整体**不可能**是 `passed`；
  3. 计数自洽：`n_failed`/`n_inconclusive` 必须与 `checks` 实算一致，`verdict` 必须能由 checks 推出。

本模块只读、不写任何被审计对象；`verdict_from_checks()` 是**判据本体**，可单测。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Iterable

#: S3 使用的两个阈值键（都在 solver_spec.thresholds 里）
S3_THRESHOLD_KEYS = ("S3_conservation_residual_max", "S3_bc_residual_max")


def verdict_from_checks(checks: Iterable[dict]) -> str:
    """fail-closed 判据：任一 `False` ⇒ failed；无 `False` 但有 `None` ⇒ inconclusive；全 `True` ⇒ passed。

    **没有第 4 种输出**：不得把 `None` 折叠成 `passed`，也不得把「未提供」写成 failed（那会错误归因）。
    """
    checks = list(checks)
    if not checks:
        return "inconclusive"
    vals = [c.get("passed") for c in checks]
    if any(v is False for v in vals):
        return "failed"
    if any(v is None for v in vals):
        return "inconclusive"
    return "passed"


def load_spec_thresholds(spec_path: str | pathlib.Path) -> dict:
    spec = json.loads(pathlib.Path(spec_path).read_text(encoding="utf-8"))
    thr = spec.get("thresholds") or {}
    return {k: thr.get(k) for k in S3_THRESHOLD_KEYS}


def audit_gate_file(gate_path: str | pathlib.Path,
                    spec_path: str | pathlib.Path) -> dict:
    """审计一个 S3 门禁件，返回 `{ok, problems, ...}`（不抛异常，也不写文件）。"""
    p = pathlib.Path(gate_path)
    problems: list[str] = []
    out: dict[str, Any] = {"gate_path": str(p), "exists": p.exists()}
    if not p.exists():
        out["problems"] = ["门禁件不存在"]
        out["ok"] = False
        return out
    doc = json.loads(p.read_text(encoding="utf-8"))
    gate = doc.get("gate") or {}
    checks = list(gate.get("checks") or [])
    n_none = sum(1 for c in checks if c.get("passed") is None)
    n_failed = sum(1 for c in checks if c.get("passed") is False)
    n_passed = sum(1 for c in checks if c.get("passed") is True)
    expect = verdict_from_checks(checks)
    expected_counts = {"n_checks": len(checks), "n_failed": n_failed,
                       "n_passed": n_passed, "n_inconclusive": n_none}
    for k, v in expected_counts.items():
        if k in gate and gate.get(k) != v:
            problems.append("计数不自洽：%s 件内 %r ≠ 实算 %r" % (k, gate.get(k), v))
    if gate.get("verdict") != expect:
        problems.append("verdict 不自洽：件内 %r ≠ 由 checks 推出的 %r" % (gate.get("verdict"), expect))
    if expect != "passed" and gate.get("release_allowed") is True:
        problems.append("release_allowed=True 但判定为 %r（不得放行）" % expect)
    if expect != "passed" and gate.get("S3_complete") is True:
        problems.append("S3_complete=True 但判定为 %r" % expect)
    # 阈值来源
    prov = gate.get("thresholds_provenance") or {}
    spec_thr = load_spec_thresholds(spec_path)
    for k, v in spec_thr.items():
        if k in prov and prov.get(k) != v:
            problems.append("阈值与 spec 不一致：%s 件内 %r ≠ spec %r" % (k, prov.get(k), v))
    if prov and prov.get("modified") not in (False, None):
        problems.append("thresholds_provenance.modified = %r（应为 false）" % prov.get("modified"))
    out.update({"ok": not problems, "problems": problems, "verdict_derived": expect,
                "counts": expected_counts, "spec_thresholds": spec_thr,
                "provenance_thresholds": {k: prov.get(k) for k in S3_THRESHOLD_KEYS},
                "n_checks_in_file": len(checks)})
    return out


def audit_supersession(new_path: str | pathlib.Path, old_path: str | pathlib.Path) -> dict:
    """审计「写回件」是否如实登记并**未改动**旧件：新件的 `supersedes.sha256` 必须等于旧件现算 sha256。"""
    import hashlib
    np_, op = pathlib.Path(new_path), pathlib.Path(old_path)
    out: dict[str, Any] = {"new": str(np_), "old": str(op)}
    if not (np_.exists() and op.exists()):
        out.update({"ok": False, "problems": ["新件或旧件不存在"]})
        return out
    doc = json.loads(np_.read_text(encoding="utf-8"))
    sup = doc.get("supersedes") or {}
    actual = hashlib.sha256(op.read_bytes()).hexdigest()
    problems = []
    if sup.get("sha256") != actual:
        problems.append("supersedes.sha256 与旧件现算值不符（旧件可能被改过）")
    if sup.get("bytes") is not None and sup["bytes"] != op.stat().st_size:
        problems.append("supersedes.bytes 与旧件现算字节不符")
    out.update({"ok": not problems, "problems": problems,
                "old_actual_sha256": actual, "old_actual_bytes": op.stat().st_size,
                "declared_sha256": sup.get("sha256"), "declared_bytes": sup.get("bytes")})
    return out
