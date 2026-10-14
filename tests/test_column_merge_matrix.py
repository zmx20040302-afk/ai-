# -*- coding: utf-8 -*-
"""列级可合并矩阵（`scripts/build_column_merge_matrix.py`）的离线自测。

覆盖的失效模式：
* 矩阵**必须**由数据表头生成，且**未分类的列一律 fail-closed**（不得默认当可并）；
* 用户裁定（结构同源）**不得**被误读成"输出列可拼接" ⇒ 当前**输出轴可并列必须为空**；
* 语义字段（poolable 的含义）必须存在，避免下游自行解释。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
import _subproc  # noqa: E402  （tests/ 目录由 pytest 加进 sys.path）
SCRIPT = REPO / "scripts/build_column_merge_matrix.py"
MATRIX = REPO / "work/runs/remote-exported-20260922/column_merge_matrix.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("_cmm", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_matrix_builds_and_is_classified():
    r = _subproc.run_py(SCRIPT)
    assert r.returncode == 0, r.stderr
    d = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert d["kind"] == "column_merge_matrix"
    assert d["ruling"]["feedback_id"].startswith("fb-")
    assert "poolable_true" in d["semantics"] and "poolable_false" in d["semantics"]
    cols = d["columns"]
    assert len(cols) >= 90
    # 每一列都必须说明理由与来源批次（可审计）
    for name, v in cols.items():
        assert v["why"], name
        assert v["axis"] in ("input", "output", "quality", "provenance"), name
        assert isinstance(v["poolable"], bool), name
        assert v["matched_rule"], name
    assert d["summary"]["n_columns"] == len(cols)


def test_ruling_does_not_imply_output_columns_are_poolable():
    """**核心纪律**（2026-09-28 按证据升级）：结构同源 ≠ 输出列可拼接。

    旧规则是"输出轴可并列必须为空"。新批（C）带来**逐列复现证据**后，
    A↔C 的原始导出量**可以**并——但必须是**有证据**地并，且：
    * 每个可并列都要列出 ≥2 个批次；
    * 输出轴的可并列**必须带 evidence**；
    * **依赖扫描范围的列一律不可并**（A 上界 35 MHz vs C 上界 50 MHz）；
    * 定义未确认的列（`Vave`/`Vcenter`/`Ptot`/`Zin*`）仍不可并。
    """
    d = json.loads(MATRIX.read_text(encoding="utf-8"))
    cols = d["columns"]
    # ① 输入轴可并
    assert set(d["summary"]["input_poolable"]) == {"x_scale", "N_w_te1", "N_w_te2", "freq_Hz"}
    # ② 每个可并列：≥2 批次；输出轴必须有证据且只跨 A↔C
    for name, v in cols.items():
        if not v["poolable"]:
            continue
        assert len(v["poolable_batches"]) >= 2, name
        if v["axis"] == "output":
            assert v.get("evidence"), "%s 标为可并却没有证据" % name
            assert v["poolable_batches"] == ["A", "C"], name
    # ③ 范围依赖的列**一律不可并**
    rd = set(d["range_dependent_columns"])
    assert rd, "范围依赖列集合不应为空"
    for name in rd:
        assert cols[name]["poolable"] is False, name
        assert cols[name].get("depends_on") == "freq_range", name
        assert cols[name]["poolable_batches"] == [], name
    # 关键代表：全局极值 / 端点旗标 / 带宽 Q 都在名单里
    assert {"spl_max_dB", "f_peak_Hz", "peak_at_range_edge",
            "bandwidth_not_closed", "q_from_points"} <= rd
    # ④ 定义未确认的列仍不可并
    for c in ("Vcenter_20MHz_mps", "Vave_mps", "Ptot_W", "Zin1_R", "Zin1_X"):
        assert cols[c]["poolable"] is False, c
    # ⑤ 异常组合必须登记（单点批间不一致，查清前不得参与合并统计）
    assert d["anomalies"] and d["anomalies"][0]["combo"] == {"x_scale": 0.2, "N_w_te1": 1,
                                                             "N_w_te2": 7}
    # ⑥ 三批的标定差异（频率范围）必须显式记录；C 的 .mph 哈希必须入册
    assert d["batches"]["A"]["freq_range_MHz"] == [5, 35]
    assert d["batches"]["C"]["freq_range_MHz"] == [5, 50]
    assert d["batches"]["C"]["base_model_id"] is None
    assert len(d["batches"]["C"]["artifact_sha256"]) == 3


def test_unknown_column_fails_closed():
    """未分类的列必须抛错（而不是默认 poolable=True）。"""
    m = load_mod()
    with pytest.raises(KeyError):
        m.classify("some_brand_new_column_20260923")
    # 已分类的列命中
    rule, matched = m.classify("x_scale")
    assert rule["poolable"] is True and matched == "explicit"
    rule, matched = m.classify("flag_peak_at_range_edge")
    assert rule["poolable"] is True and matched.startswith("bulk:")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
