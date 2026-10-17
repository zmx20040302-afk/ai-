"""离线核对冻结的124例研究数据是否齐备；不训练、不放行、不调用COMSOL。"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import zipfile

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from memsharness.pmut_f1_operator_data import validate_plan
from memsharness.pmut_pressure_operator import load_dataset, sha256, write_new_json

EXPECTED_PLAN_SHA256 = "749efd9c394f59a90da304911dfbd0c80f09fe98dbda1ad7514e5ce67da7b2c3"
EXPECTED_PROTOCOL_SHA256 = "7ea7b9879588b4a9f320816a82359f97e29acae3ba13a8ebc23288fb071b7833"
ELIGIBLE_N2 = (5, 6, 7, 8)
EXPECTED_DESIGNS = 124
EXPECTED_EXPOSED = 21


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    def reject(value):
        raise ValueError("Nonfinite JSON value: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=reject)


def check_readiness(plan_path, protocol_path, dataset_path):
    """完整性结论仅由固定证据+ID集合+实际文件验收决定，不采信intake_passed。"""
    paths = {"plan": Path(plan_path).resolve(), "research_protocol": Path(protocol_path).resolve(), "dataset": Path(dataset_path).resolve()}
    result = {
        "schema": "memsharness.pmut_operator_research_readiness/v0", "scope": "frozen_research_dataset_completeness_only",
        "research_dataset_complete": False, "cross_branch_research_training_blocked": True,
        "frozen_inputs_valid": False, "dataset_file_validation_passed": False, "frozen_case_binding_passed": False,
        "required_eligible_designs": EXPECTED_DESIGNS, "required_eligible_N_w_te2": list(ELIGIBLE_N2),
        "received_unique_designs": 0, "missing_eligible_case_ids": [], "unexpected_case_ids": [],
        "quarantined_included_case_ids": [], "duplicate_case_ids": [], "split_mismatches": [],
        "previously_exposed_in_test": [], "case_binding_errors": [], "validation_errors": [],
        "input_paths": {key: str(value) for key, value in paths.items()}, "input_sha256": {},
        "expected_plan_sha256": EXPECTED_PLAN_SHA256, "expected_protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "training_ready": False, "release_allowed": False, "physics_inputs_complete": False,
        "physical_mapping_verified": False, "first_mode_identified": False, "field_error_bound_verified": False,
        "training_executed": False, "network_used": False, "comsol_solve_requested": False,
        "next_action": "wait_for_missing_or_invalid_evidence_no_training",
        "limitations": ["Completeness is not physics certification, a first-mode identity, or a field error bound.",
            "No training is executed or model release granted; only the frozen research dataset is checked.",
            "The dataset loader validates NPZ bytes/arrays; this tool does not re-read original COMSOL models or revalidate every source MAT.",
            "Saved-solution geometry and oracle frequencies do not demonstrate solver-free inference on new designs."]}
    try:
        for key, path in paths.items():
            result["input_sha256"][key] = sha256(path)
        if result["input_sha256"]["plan"] != EXPECTED_PLAN_SHA256:
            raise ValueError("Frozen plan SHA256 does not match the authorized plan")
        if result["input_sha256"]["research_protocol"] != EXPECTED_PROTOCOL_SHA256:
            raise ValueError("Research protocol SHA256 does not match the frozen protocol")
        protocol = strict_json(paths["research_protocol"])
        if not (protocol.get("schema") == "memsharness.pmut_operator_research_protocol/v0"
                and protocol.get("frozen_plan_sha256") == EXPECTED_PLAN_SHA256
                and protocol.get("required_accepted_N_w_te2") == list(ELIGIBLE_N2)
                and type(protocol.get("required_accepted_designs_for_cross_branch_experiment")) is int
                and protocol["required_accepted_designs_for_cross_branch_experiment"] == EXPECTED_DESIGNS
                and protocol.get("training_ready") is False and protocol.get("release_allowed") is False
                and protocol.get("physics_inputs_complete") is False and protocol.get("training", {}).get("research_only") is True):
            raise ValueError("Frozen protocol semantic contract mismatch")
        manifest = strict_json(paths["dataset"])
        if not isinstance(manifest, dict):
            raise ValueError("Dataset manifest must be an object")
        policy = manifest.get("split_policy")
        if policy not in protocol.get("split_policies", []):
            raise ValueError("Dataset split policy is not frozen in the protocol")
        strict_json(paths["plan"])
        _, planned = validate_plan(paths["plan"], policy)
        eligible = {cid: case for cid, case in planned.items() if case["N_w_te2"] in ELIGIBLE_N2
                    and case.get("training_eligibility") != "lineage_quarantine"
                    and not case.get("lineage_alignment_pending", False) and not case["selection"].get("lineage_quarantine", False)}
        exposed = {cid for cid, case in planned.items() if case["selection"].get("previously_exposed", False)}
        if len(eligible) != EXPECTED_DESIGNS or len(exposed) != EXPECTED_EXPOSED or not exposed <= set(eligible):
            raise ValueError("Frozen eligible/exposed population mismatch")
        result.update(frozen_inputs_valid=True, split_policy=policy, expected_eligible_case_ids=sorted(eligible),
                      planned_quarantine_case_ids=sorted(set(planned) - set(eligible)), previously_exposed_case_ids=sorted(exposed))
        cases = manifest.get("cases")
        if not isinstance(cases, list) or any(not isinstance(case, dict) or not isinstance(case.get("case_id"), str) for case in cases):
            raise ValueError("Invalid dataset case list")
        counts = Counter(case["case_id"] for case in cases)
        received = set(counts)
        result.update(received_unique_designs=len(received), received_case_rows=len(cases),
            missing_eligible_case_ids=sorted(set(eligible) - received), unexpected_case_ids=sorted(received - set(eligible)),
            quarantined_included_case_ids=sorted(received & (set(planned) - set(eligible))),
            duplicate_case_ids=sorted(cid for cid, count in counts.items() if count != 1),
            received_eligible_designs=len(received & set(eligible)),
            missing_eligible_designs=len(set(eligible) - received),
            received_by_N_w_te2=dict(sorted(Counter(str(eligible[cid]["N_w_te2"]) for cid in received & set(eligible)).items())))
        if manifest.get("plan_sha256") != EXPECTED_PLAN_SHA256:
            result["validation_errors"].append("Dataset is not bound to the exact frozen plan SHA256")
        if manifest.get("training_ready") is not False or manifest.get("release_allowed") is not False:
            result["validation_errors"].append("Dataset makes an unexpected training/release claim")
        for case in cases:
            cid = case["case_id"]
            if cid in exposed and case.get("split") == "test":
                result["previously_exposed_in_test"].append(cid)
            if cid in eligible:
                target = eligible[cid]
                expected_split = target["selection"]["training_splits"][policy]
                if case.get("split") != expected_split:
                    result["split_mismatches"].append({"case_id": cid, "expected": expected_split, "actual": case.get("split")})
                if case.get("design_id") != target["design_id"] or case.get("branch_id") != target["branch_id"]:
                    result["case_binding_errors"].append({"case_id": cid, "error": "Frozen design/branch identity differs"})
        # 即使数量/ID不足也执行已有逐文件验收：完整性失败与缺数分别留痕。
        dataset = load_dataset(paths["dataset"], research_only=True)
        result["dataset_file_validation_passed"] = True
        result["physics_and_inference_blockers"] = dataset.blockers
        names = [feature["name"] for feature in manifest["context_features"]]
        required = ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz")
        if any(name not in names for name in required):
            result["validation_errors"].append("Context lacks explicit three parameters/frequency for frozen-design binding")
        else:
            for case in dataset.cases:
                cid = case.metadata["case_id"]
                if cid not in eligible:
                    continue
                target = eligible[cid]
                errors = []
                for name in required:
                    actual = float(case.context[names.index(name)])
                    tolerance = 1. if name == "frequency_Hz" else 5e-9 if name == "x_scale" else 0.
                    if abs(actual - target[name]) > tolerance:
                        errors.append("Context differs from frozen " + name)
                for name, expected in {"source_type": "simulation", "frequency_source": "stored_solution_oracle",
                    "mode_identity": "unverified", "input_provenance": "saved_solution_evaluation_geometry"}.items():
                    if case.metadata.get(name) != expected:
                        errors.append("Research protocol scope differs: " + name)
                finite = np.isfinite(case.target_pressure_ri_Pa).all(axis=1)
                if not np.array_equal(case.loss_mask, finite):
                    errors.append("Pressure mask must exactly identify finite field labels")
                truth = complex(float(target["p_point_real_Pa"]), float(target["p_point_imag_Pa"]))
                observed = complex(*case.exact_pressure_ri_Pa.reshape(2))
                if abs(observed - truth) > 1e-9 + 1e-6 * abs(truth):
                    errors.append("Exact-point complex label differs from frozen scalar reference")
                result["case_binding_errors"].extend({"case_id": cid, "error": error} for error in errors)
        # 读取期间发生任何证据更改都会失败，不接受先后混合快照。
        for key, path in paths.items():
            if sha256(path) != result["input_sha256"][key]:
                result["validation_errors"].append("Input changed during readiness check: " + key)
        for case in dataset.cases:
            path = paths["dataset"].parent / case.metadata["npz"]
            if sha256(path) != case.metadata["sha256"]:
                result["validation_errors"].append("NPZ changed during readiness check: " + case.metadata["case_id"])
        result["frozen_case_binding_passed"] = not result["case_binding_errors"] and not result["split_mismatches"] and not result["previously_exposed_in_test"]
        complete = (received == set(eligible) and len(cases) == EXPECTED_DESIGNS and not result["duplicate_case_ids"]
                    and result["frozen_case_binding_passed"] and not result["validation_errors"])
        result["research_dataset_complete"] = bool(complete)
        result["cross_branch_research_training_blocked"] = not complete
        if complete:
            result["next_action"] = "review_frozen_protocol_then_explicit_research_only_experiment_not_production_release"
    except (ValueError, OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile) as error:
        result["validation_errors"].append(type(error).__name__ + ": " + str(error))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--research-protocol", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New append-only JSON report; parent must exist")
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("Readiness report must be a new path")
    report = check_readiness(args.plan, args.research_protocol, args.dataset)
    write_new_json(args.output, report)
    print(json.dumps({"research_dataset_complete": report["research_dataset_complete"],
        "cross_branch_research_training_blocked": report["cross_branch_research_training_blocked"],
        "received_eligible_designs": report.get("received_eligible_designs", 0),
        "required_eligible_designs": EXPECTED_DESIGNS, "missing_eligible_designs": report.get("missing_eligible_designs"),
        "training_ready": False, "release_allowed": False, "report_sha256": sha256(args.output), "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0 if report["research_dataset_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
