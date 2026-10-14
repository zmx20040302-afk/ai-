# -*- coding: utf-8 -*-
"""身份标识与统一骨架的离线自测。

锁住的裁定（`feedback` `fb-20260923T142102Z-4bd9fd86`）：
* 哈希取得前 `base_model_id` 必须是 NULL + `pending_sha256`；
* **不得用文件名/路径冒充 `base_model_id`**（这条必须是代码事实，不是文档里的一句话）；
* 统一骨架**只含身份 + 输入轴**，不得携带任何输出值（输出轴可并列实测为 0）。
"""
from __future__ import annotations

import csv
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
import _subproc  # noqa: E402  （tests/ 目录由 pytest 加进 sys.path）
sys.path.insert(0, str(REPO / "src"))

from memsharness.identity import (IdentityViolation, assert_base_model_id,  # noqa: E402
                                 measurement_profile_id, parameter_set_id,
                                 pending_identity)

RUN = REPO / "work/runs/remote-exported-20260922"
SKEL = RUN / "unified_skeleton.csv"
SKEL_SCRIPT = REPO / "scripts/build_unified_skeleton.py"


def test_base_model_id_rejects_filenames():
    ok = "a" * 64
    assert assert_base_model_id(ok) == ok
    assert assert_base_model_id(ok.upper()) == ok
    assert assert_base_model_id(None) is None
    assert assert_base_model_id("") is None
    for bad in ("cell_te2_9_v1.mph", "b_GE_task3_2-new.mph", "path/to/model", "C:\\x\\y.mph",
                "cell_te2_9_v1", "model.m"):
        with pytest.raises(IdentityViolation):
            assert_base_model_id(bad)


def test_pending_identity_is_null_and_labelled():
    b = pending_identity(identity_basis="user_confirmed_same_base_model",
                         source_file="cell_te2_9_v1.mph", run_id="run-x")
    assert b["base_model_id"] is None
    assert b["base_model_id_status"] == "pending_sha256"
    assert b["artifact_sha256"] is None
    assert b["configuration_id"] is None and b["measurement_profile_id"] is None
    # 文件名只能待在**溯源**字段里
    assert b["source_file"] == "cell_te2_9_v1.mph"
    assert b["identity_basis"] == "user_confirmed_same_base_model"


def test_parameter_set_id_stable_and_float_normalised():
    a = parameter_set_id({"x_scale": 0.3, "N_w_te1": 2, "N_w_te2": 7})
    b = parameter_set_id({"N_w_te2": 7, "N_w_te1": 2, "x_scale": 0.30000000000000004})
    c = parameter_set_id({"x_scale": 0.3, "N_w_te1": 2, "N_w_te2": 8})
    assert a == b, "浮点表示差异不得产生不同指纹"
    assert a != c
    assert a.startswith("ps-")
    with pytest.raises(ValueError):
        parameter_set_id({"x_scale": 0.3, "N_w_te1": 2})


def test_measurement_profile_requires_all_four():
    assert measurement_profile_id(point_m=[0, 0, -1e-5]) == (None, "pending_profile")
    assert measurement_profile_id(point_m=[0, 0, -1e-5], surface="table9",
                                  expressions={"p": "acpr.p_t"}) == (None, "pending_profile")
    mid, st = measurement_profile_id(point_m=[0, 0, -1e-5], surface="table9",
                                     expressions={"p": "acpr.p_t"}, units={"p": "Pa"})
    assert mid is not None and st == "sha256_present"
    assert mid.startswith("mp-")


def test_skeleton_has_no_output_values(monkeypatch, tmp_path):
    r = _subproc.run_py(SKEL_SCRIPT, "--check")
    assert r.returncode == 0, r.stderr
    assert SKEL.is_file()
    mm = json.loads((RUN / "column_merge_matrix.json").read_text(encoding="utf-8"))
    poolable = {k for k, v in mm["columns"].items() if v["poolable"]}
    with SKEL.open(encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames
        rows = list(rd)
    # ① 骨架里的每个值列都必须是矩阵标为可并的
    value_cols = [c for c in cols if c not in
                  ("batch", "base_model_id", "base_model_id_status", "artifact_sha256",
                   "configuration_id", "parameter_set_id", "measurement_profile_id",
                   "run_id", "identity_basis", "source_file", "source_path", "run_name")]
    assert set(value_cols) <= poolable, value_cols
    # ② base_model_id 必须全空（pending_sha256），且状态码正确
    assert all(r["base_model_id"] == "" for r in rows)
    assert {r["base_model_id_status"] for r in rows} == {"pending_sha256"}
    assert {r["identity_basis"] for r in rows} == {"user_confirmed_same_base_model"}
    # ③ 数据 B 行缺 N2 ⇒ 不给 parameter_set_id（不猜）；A/C 必须给
    b_rows = [r for r in rows if r["batch"] == "B"]
    a_rows = [r for r in rows if r["batch"] == "A"]
    c_rows = [r for r in rows if r["batch"] == "C"]
    assert b_rows and a_rows and c_rows
    assert all(r["parameter_set_id"] == "" for r in b_rows)
    assert all(r["parameter_set_id"].startswith("ps-") for r in a_rows)
    assert all(r["parameter_set_id"].startswith("ps-") for r in c_rows)
    # ④ 三批行数与数据一致
    assert len(a_rows) == 13603 and len(b_rows) == 490
    assert len(c_rows) == 110565                     # 1215 组合 × 91 频点
    # ⑤ 不得出现任何输出量列名
    for c in ("spl_dB", "p_abs_Pa", "Vave_mps", "Ptot_W", "Zin1_R"):
        assert c not in cols, c
    # ⑥ **批次 C 的 artifact_sha256 必须来自远端 model_manifest.tsv（真哈希）**
    hex64 = re.compile(r"^[0-9a-f]{64}$")
    assert all(hex64.match(r["artifact_sha256"] or "") for r in c_rows), \
        "C 的 artifact_sha256 必须是 64 位十六进制"
    assert len({r["artifact_sha256"] for r in c_rows}) == 3, "三个 run 三个哈希"
    assert all(r["artifact_sha256"] == "" for r in a_rows + b_rows), "A/B 尚未取到 .mph 哈希"
    # ⑦ C 的来源字段指向 .mph 名与远端路径
    assert all(r["source_file"].endswith(".mph") for r in c_rows)
    assert all("autodesign" in r["source_path"] for r in c_rows)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
