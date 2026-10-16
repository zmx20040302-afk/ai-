"""PMUT-F1 三参数副本写入入口的纯逻辑测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from memsharness.pmut_f1 import PmutF1ContractError


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/pmut_f1_copy_params.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_pmut_f1_copy_params_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parameter_expressions_include_exactly_three_frozen_parameters():
    mod = _load_script()
    assert mod.parameter_expressions(0.61, 5, 8) == {
        "x_scale": "0.61",
        "N_w_te1": "5",
        "N_w_te2": "8",
    }


def test_parameter_expressions_reject_invalid_discrete_branch():
    mod = _load_script()
    with pytest.raises(PmutF1ContractError):
        mod.parameter_expressions(0.61, 8, 8)


@pytest.mark.parametrize("geometry_ok", [True, False, None])
def test_geometry_failure_blocks_success_and_selections_always_need_verification(geometry_ok):
    mod = _load_script()
    requested = mod.parameter_expressions(0.61, 5, 8)
    result = {
        "ok": True, "source_original_untouched": True,
        "diff": [{"name": name, "applied": True} for name in requested],
        "geometry_after_set": {"rebuilt_ok": geometry_ok},
        "required_reverification": False,
    }
    status = mod.evaluate_copy_result(result, requested, "hash", "hash")
    assert status["parameter_write_ok"] is True
    assert status["ok"] is (geometry_ok is True)
    assert status["required_reverification"] is True
    assert status["ready_for_solve"] is False
