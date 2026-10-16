"""PMUT 一阶频率单点/场级闭环的冻结任务合同与覆盖计算。

本模块只负责合同、适用域、覆盖状态和验证请求载荷；它不直接启动 COMSOL，
也不修改生产模型。真实改参必须交给 :func:`memsharness.modelio.set_parameters`
的副本写入通路，长求解必须进入串行异步队列。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping


REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO / "work/dist/pmut-f1-v0/contract.json"


class PmutF1ContractError(ValueError):
    """任务合同或候选点不满足冻结约束。"""


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """读取并验证 PMUT-F1 合同。"""

    contract_path = Path(path)
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    validate_contract(payload)
    return payload


def _integer_n2_values(contract: Mapping[str, Any]) -> tuple[int, ...]:
    values = contract["parameters"]["N_w_te2"]["values"]
    if not values or any(isinstance(value, bool) or int(value) != value for value in values):
        raise PmutF1ContractError("N_w_te2.values 必须是非空整数列表")
    result = tuple(int(value) for value in values)
    if len(result) != len(set(result)) or tuple(sorted(result)) != result:
        raise PmutF1ContractError("N_w_te2.values 必须严格升序且不重复")
    return result


def _x_grid(contract: Mapping[str, Any]) -> tuple[float, ...]:
    spec = contract["parameters"]["x_scale"]
    lo, hi = (float(value) for value in spec["range"])
    step = float(spec["validation_grid_step"])
    if not math.isfinite(lo) or not math.isfinite(hi) or not math.isfinite(step):
        raise PmutF1ContractError("x_scale 范围与步长必须是有限数")
    if lo >= hi or step <= 0:
        raise PmutF1ContractError("x_scale 必须满足 lo < hi 且 step > 0")
    intervals = round((hi - lo) / step)
    if not math.isclose(lo + intervals * step, hi, rel_tol=0.0, abs_tol=1e-12):
        raise PmutF1ContractError("x_scale 验证步长必须精确落到上界")
    return tuple(round(lo + index * step, 12) for index in range(intervals + 1))


def enumerate_design_grid(
    contract: Mapping[str, Any], *, n2_values: tuple[int, ...] | None = None
) -> list[dict[str, float | int]]:
    """枚举冻结验证网格；N1/N2 是离散分支，禁止把它们当连续变量插值。"""

    xs = _x_grid(contract)
    allowed_n2 = _integer_n2_values(contract)
    chosen = allowed_n2 if n2_values is None else tuple(int(value) for value in n2_values)
    unknown = sorted(set(chosen) - set(allowed_n2))
    if unknown:
        raise PmutF1ContractError("N_w_te2 不在冻结域：%s" % unknown)
    return [
        {"x_scale": x, "N_w_te1": n1, "N_w_te2": n2}
        for n2 in chosen
        for n1 in range(1, n2)
        for x in xs
    ]


def validate_contract(contract: Mapping[str, Any]) -> None:
    """对关键物理口径和数据计数做 fail-closed 自校验。"""

    if contract.get("schema") != "memsharness.pmut_f1_contract/v0":
        raise PmutF1ContractError("未知 PMUT-F1 合同 schema")
    observation = contract["objective"]["observation"]
    xyz = tuple(float(value) for value in observation["xyz_m"])
    if (observation.get("coordinate_system") != "model_global"
            or observation.get("side") != "below" or xyz != (0.0, 0.0, -1e-5)):
        raise PmutF1ContractError("冻结观测点必须是下方 (0,0,-10 um)")
    if contract["objective"].get("frequency_policy") != "per_design_first_mode":
        raise PmutF1ContractError("频率策略必须是逐设计第一阶频率")
    if contract["objective"].get("field_alias") != "p_total_Pa":
        raise PmutF1ContractError("当前合同只允许 p_total_Pa")
    if contract["objective"].get("field_expression") != "acpr.p_t":
        raise PmutF1ContractError("冻结场表达式必须是 acpr.p_t")

    all_grid = enumerate_design_grid(contract)
    known = contract["known_scalar_data"]
    if tuple(known["observation_xyz_m"]) != xyz:
        raise PmutF1ContractError("已登记标量数据观测点必须与目标一致")
    x_spec = contract["parameters"]["x_scale"]
    if (known["x_scale"]["range"] != x_spec["range"]
            or known["x_scale"]["step"] != x_spec["validation_grid_step"]):
        raise PmutF1ContractError("当前覆盖计算要求已登记标量网格与验证网格一致")
    known_n2 = tuple(int(value) for value in known["N_w_te2"])
    known_grid = enumerate_design_grid(contract, n2_values=known_n2)
    if len(_x_grid(contract)) != int(known["x_scale"]["count"]):
        raise PmutF1ContractError("x_scale 网格点数与已登记数据不一致")
    if len(known_grid) != int(known["n_designs"]):
        raise PmutF1ContractError("已登记标量设计数与冻结网格不一致")
    found = int(known["n_first_peak_found"])
    missing_peak = int(known["n_first_peak_not_found_in_window"])
    if found + missing_peak != len(known_grid):
        raise PmutF1ContractError("首峰找到/未找到计数不能覆盖全部已知设计")
    if contract["execution_policy"].get("production_model_read_only") is not True:
        raise PmutF1ContractError("生产模型必须保持只读")
    if contract["execution_policy"].get("model_write") != "copy_only":
        raise PmutF1ContractError("PMUT-F1-v0 只允许 copy_only")
    if contract["execution_policy"].get("comsol_execution") != "serial_only":
        raise PmutF1ContractError("COMSOL 必须串行执行")
    modeling = contract.get("modeling_policy") or {}
    if modeling.get("primary_model_family") != "geometry_conditioned_neural_operator":
        raise PmutF1ContractError("PMUT-F1 目标模型必须是几何条件神经算子")
    if modeling.get("interpolation_as_solver") != "forbidden":
        raise PmutF1ContractError("参数插值不得作为 PMUT-F1 目标求解器")
    if modeling.get("zero_shot_release") != "forbidden_without_independent_validation":
        raise PmutF1ContractError("新模型未经独立验证不得零样本放行")
    if not all_grid:
        raise PmutF1ContractError("冻结设计域不能为空")


def coverage_summary(contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """返回网页和编排器共享的三参数覆盖状态。"""

    current = dict(contract or load_contract())
    validate_contract(current)
    all_n2 = _integer_n2_values(current)
    known_n2 = tuple(int(value) for value in current["known_scalar_data"]["N_w_te2"])
    xs = _x_grid(current)
    by_n2 = []
    for n2 in all_n2:
        total = (n2 - 1) * len(xs)
        available = total if n2 in known_n2 else 0
        by_n2.append({
            "N_w_te2": n2,
            "N_w_te1_values": list(range(1, n2)),
            "n_total": total,
            "n_scalar_registered": available,
            "n_missing": total - available,
            "status": "scalar_spectrum_registered" if available == total else "not_registered",
        })
    total = sum(row["n_total"] for row in by_n2)
    available = sum(row["n_scalar_registered"] for row in by_n2)
    known = current["known_scalar_data"]
    return {
        "schema": "memsharness.pmut_f1_coverage/v0",
        "task_id": current["task_id"],
        "model_state": current["model_state"],
        "coverage_basis": "registered_inventory_not_live_data_verification",
        "operator_training_status": "not_trained",
        "observation": current["objective"]["observation"],
        "objective": current["objective"],
        "parameter_domain": current["parameters"],
        "validation_grid": {
            "n_x": len(xs),
            "n_discrete_branches": sum(n2 - 1 for n2 in all_n2),
            "n_designs_total": total,
            "n_scalar_spectrum_registered": available,
            "n_scalar_spectrum_missing": total - available,
            "by_n2": by_n2,
        },
        "first_peak": {
            "n_found": int(known["n_first_peak_found"]),
            "n_not_found_in_registered_window": int(known["n_first_peak_not_found_in_window"]),
            "frequency_grid_Hz": known["frequency_grid_Hz"],
            "not_found_action": "extend_low_frequency_scan_before_field_training",
        },
        "field_coverage": current["known_field_data"],
        "mode_identity_gate": current["mode_identity_gate"],
        "modeling_policy": current["modeling_policy"],
        "execution_policy": current["execution_policy"],
        "not_claimed": current["not_claimed"],
        "ready_for_full_loop": False,
        "blocking_gaps": [
            "N_w_te2=9: select sparse calibration/holdout designs; do not automatically sweep all 648 candidates",
            "first-mode recovery for designs without a peak in 5-50 MHz",
            "first-mode complex fields for operator training and independent holdout",
            "geometry/material/boundary-condition encoding shared across models",
            "operator transfer evaluation on unseen model geometries",
            "prediction-to-model-copy-to-COMSOL validation handoff",
        ],
    }


def validate_design_point(
    x_scale: float, n1: int | float, n2: int | float,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """验证候选点并明确已有数据层级；不返回未经验证的声压数字。"""

    current = dict(contract or load_contract())
    validate_contract(current)
    if any(isinstance(value, bool) for value in (x_scale, n1, n2)):
        raise PmutF1ContractError("设计参数不能是布尔值")
    try:
        x, n1_value, n2_value = float(x_scale), float(n1), float(n2)
    except (TypeError, ValueError) as exc:
        raise PmutF1ContractError("三个设计参数必须是数字") from exc
    if not all(math.isfinite(value) for value in (x, n1_value, n2_value)):
        raise PmutF1ContractError("三个设计参数必须是有限数")
    if int(n1_value) != n1_value or int(n2_value) != n2_value:
        raise PmutF1ContractError("N_w_te1/N_w_te2 必须是整数")
    n1_int, n2_int = int(n1_value), int(n2_value)
    lo, hi = (float(value) for value in current["parameters"]["x_scale"]["range"])
    if not lo <= x <= hi:
        raise PmutF1ContractError("x_scale 必须在 [%.2f, %.2f]" % (lo, hi))
    if n2_int not in _integer_n2_values(current):
        raise PmutF1ContractError("N_w_te2 必须是 %s" % list(_integer_n2_values(current)))
    if not 1 <= n1_int < n2_int:
        raise PmutF1ContractError("必须满足 1 <= N_w_te1 < N_w_te2")
    known_n2 = set(int(value) for value in current["known_scalar_data"]["N_w_te2"])
    sampled_x = any(math.isclose(x, value, rel_tol=0.0, abs_tol=1e-12)
                    for value in _x_grid(current))
    scalar_registered = n2_int in known_n2 and sampled_x
    field = current["known_field_data"]
    raw_field_branch = n2_int in field["N_w_te2"] and n1_int in field["N_w_te1"]
    return {
        "in_domain": True,
        "parameters": {"x_scale": x, "N_w_te1": n1_int, "N_w_te2": n2_int},
        "branch_id": "N1_%d__N2_%d" % (n1_int, n2_int),
        "observation_xyz_m": current["objective"]["observation"]["xyz_m"],
        "in_domain_means": "design_search_domain_not_validated_operator_applicability",
        "scalar_spectrum_registered": scalar_registered,
        "on_registered_x_grid": sampled_x,
        "coverage_basis": "registered_inventory_not_live_data_verification",
        "operator_training_status": "not_trained",
        "operator_prediction_available": False,
        "first_mode_operator_dataset_ready": False,
        "fixed_20MHz_raw_field_branch_registered": raw_field_branch,
        "fixed_20MHz_released_draft_branch_registered": (
            n2_int in field["N_w_te2"] and n1_int in field["released_solver_N_w_te1"]
        ),
        "action": (
            "locate_and_verify_first_mode_then_queue_operator_training_or_holdout_field"
            if scalar_registered else
            "consider_sparse_sampling_or_saved_solution_reuse_before_serial_comsol"
        ),
        "release_allowed": False,
    }


def build_validation_handoff(
    *, x_scale: float, n1: int | float, n2: int | float,
    source_model: Mapping[str, Any], prediction: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """生成 MEMS → COMSOL EDA 的只读模型/副本写入验证载荷。"""

    current = dict(contract or load_contract())
    point = validate_design_point(x_scale, n1, n2, current)
    model_path = str(source_model.get("path") or "").strip()
    model_sha = str(source_model.get("sha256") or "").strip()
    if not model_path.lower().endswith(".mph"):
        raise PmutF1ContractError("source_model.path 必须指向 .mph")
    if model_sha and (len(model_sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in model_sha)):
        raise PmutF1ContractError("source_model.sha256 必须为空或 64 位十六进制")
    predicted = dict(prediction or {})
    return {
        "schema": "memsharness.pmut_f1_validation_handoff/v0",
        "task_id": current["task_id"],
        "source_model": {"path": model_path, "sha256": model_sha or None, "read_only": True},
        "model_write": "copy_only",
        "parameters": point["parameters"],
        "observation": current["objective"]["observation"],
        "frequency_policy": "per_design_first_mode",
        "field_expression": current["objective"]["field_expression"],
        "prediction": predicted or None,
        "required_steps": [
            "copy_source_model",
            "write_and_read_back_all_three_parameters",
            "rebuild_geometry",
            "verify_named_selections",
            "locate_and_verify_first_mode",
            "evaluate_complex_pressure_at_exact_observation_point",
            "export_complex_pressure_field",
            "compare_prediction_with_independent_comsol_result",
        ],
        "execution": "serial_only",
        "human_release_required": True,
        "status": "handoff_plan_only_not_submitted",
        "execution_ready": False,
        "release_allowed": False,
    }

