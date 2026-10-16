"""按完整几何冻结稀疏选样；不插值、不推算解索引、不启动求解。"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from .pmut_f1_dataset import design_key, sha256, write_new_json


SCHEMA = "memsharness.pmut_f1_sparse_plan/v0"
DEFAULT_SEED = "pmut-f1-sparse-v1"
HASH = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_id(record):
    x, n1, n2 = design_key(record["x_scale"], record["N_w_te1"], record["N_w_te2"])
    return "x%03d_N1%d_N2%d" % (round(x * 100), n1, n2)


def branch_id(record):
    return "N1%d_N2%d" % (record["N_w_te1"], record["N_w_te2"])


def rank(seed, label):
    return hashlib.sha256((seed + "\0" + label).encode("utf-8")).hexdigest()


def read_historical_hints(path=None, model_path_hints=()):
    """历史路径/哈希仅作线索，绝不提升为本轮 source_hash_verified。"""
    hints = {}
    if path is not None:
        path = Path(path)
        evidence = {"path": str(path.resolve()), "sha256": sha256(path)}
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                match = re.search(r"cell_te2_([5-9])_", row["model_path"])
                require(match is not None, "Cannot identify historical filename hint")
                n2 = int(match.group(1))
                require(n2 not in hints and HASH.fullmatch(row["sha256"]) is not None, "Duplicate/invalid historical hint")
                hints[n2] = {"source_model": row["model_path"], "historical_source_model_sha256": row["sha256"],
                             "historical_size_bytes": int(row["size_bytes"]), "historical_evidence": evidence,
                             "branch_link_basis": "filename_hint_not_physics_identity_verification"}
    for hint in model_path_hints:
        n2_text, sep, model_path = hint.partition("=")
        require(sep and n2_text in {"5", "6", "7", "8", "9"} and model_path.endswith(".mph"), "Invalid N2=model.mph hint")
        n2 = int(n2_text)
        require(n2 not in hints or hints[n2]["source_model"] == model_path, "Conflicting model path hint")
        hints.setdefault(n2, {"source_model": model_path, "historical_source_model_sha256": None,
                              "branch_link_basis": "explicit_path_hint_not_physics_identity_verification"})
    return hints


def _validated_records(inventory):
    require(inventory.get("schema") == "memsharness.pmut_f1_scalar_inventory/v0", "Wrong scalar inventory schema")
    records = inventory["records"]
    require(len(records) == inventory["n_designs"], "Inventory count mismatch")
    source_hashes = {}
    for source in inventory["sources"]:
        n2 = source["N_w_te2"]
        require(n2 in range(5, 10) and n2 not in source_hashes, "Duplicate/invalid scalar source layer")
        source_hashes[n2] = source["sha256"]
    require(set(source_hashes) == set(range(5, 10)), "Five registered scalar layers are required")
    indexed = {}
    for record in records:
        cid = canonical_id(record)
        require(record["case_id"] == cid and cid not in indexed, "Duplicate or noncanonical complete geometry")
        require(record["source_type"] == "simulation" and record["observation_xyz_m"] == [0, 0, -1e-5], "Wrong source/observation")
        require(record["field_expression"] == "acpr.p_t" and record["mode_identity"] == "unverified", "Unexpected field/mode identity")
        require(HASH.fullmatch(record["source_table_sha256"]) is not None, "Invalid source table hash")
        require(record["source_table_sha256"] == source_hashes[record["N_w_te2"]], "Scalar record/source layer mismatch")
        if record["first_observable_peak_found"]:
            values = [record[k] for k in ("frequency_Hz", "p_point_real_Pa", "p_point_imag_Pa")]
            require(all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in values), "Invalid peak values")
            require(record["frequency_Hz"] > 0 and int(record["source_table_row_1based"]) >= 1, "Invalid peak row/frequency")
        indexed[cid] = record
    expected = {"x%03d_N1%d_N2%d" % (ix, n1, n2) for ix in range(20, 101)
                for n2 in range(5, 10) for n1 in range(1, n2)}
    require(set(indexed) == expected, "Scalar inventory does not cover the frozen full geometry grid")
    return indexed


def freeze_splits(records, exposed, seed=DEFAULT_SEED):
    """先于选样冻结所有几何；不查看压力大小、相位或目标极值。"""
    require(set(exposed) <= set(records), "Exposed case is absent from inventory")
    branch_groups = defaultdict(list)
    exposed_branches = {branch_id(records[cid]) for cid in exposed}
    for record in records.values():
        branch_groups[record["N_w_te2"]].append(branch_id(record))
    branch_splits = {}
    for n2, repeated in sorted(branch_groups.items()):
        branches = sorted(set(repeated))
        fresh = sorted((b for b in branches if b not in exposed_branches), key=lambda b: rank(seed, "branch:" + b))
        ntest = max(1, round(len(fresh) * .2)) if len(fresh) >= 2 else 0
        ndev = max(1, round(len(fresh) * .2)) if len(fresh) >= 3 else 0
        for i, bid in enumerate(fresh):
            branch_splits[bid] = "test" if i < ntest else "dev" if i < ntest + ndev else "train"
        branch_splits.update({b: "dev" for b in branches if b in exposed_branches})
    splits = {}
    for cid, record in sorted(records.items()):
        bucket = int(rank(seed, "design:" + cid)[:8], 16) % 100
        parameter = "dev" if cid in exposed else "train" if bucket < 60 else "dev" if bucket < 80 else "test"
        split = {"parameter_holdout": parameter, "branch_holdout": branch_splits[branch_id(record)]}
        splits[cid] = {"case_id": cid, "geometry_id": cid, "design_id": cid, "branch_id": branch_id(record),
                       "splits": split, "training_splits": {"design_holdout": "validation" if parameter == "dev" else parameter,
                          "branch_holdout": "validation" if split["branch_holdout"] == "dev" else split["branch_holdout"]},
                       "previously_exposed": cid in exposed,
                       "lineage_quarantine": bool(record.get("lineage_alignment_pending", False))}
    return splits


def spaced_x(records, count):
    ordered = sorted(records, key=lambda r: (r["x_scale"], r["case_id"]))
    count = min(count, len(ordered))
    if count == 0:
        return []
    if count == 1:
        return [ordered[len(ordered) // 2]]
    return [ordered[round(i * (len(ordered) - 1) / (count - 1))] for i in range(count)]


def _source_index_map(index):
    if index is None:
        return {}
    require(index.get("schema") == "memsharness.pmut_f1_source_index/v0", "Wrong source index schema")
    out = {}
    for source in index["sources"]:
        key = source["source_table_sha256"]
        require(HASH.fullmatch(key) is not None and key not in out, "Duplicate/invalid index source")
        out[key] = source
    return out


def resolve_indices(record, sources):
    """只接受带实际读回证据的索引；不使用Table行号、频率行位置或stride推导。"""
    pending = {"outer_solnum": None, "inner_solnum": None, "export_ready": False,
               "index_status": "pending_source_and_solution_readback", "source_model_sha256": None,
               "source_hash_verified": False, "pending_reasons": []}
    source = sources.get(record["source_table_sha256"])
    if source is None:
        pending["pending_reasons"] = ["source_index_not_provided"]
        return pending
    if source.get("source_hash_verified") is not True:
        pending["pending_reasons"] = ["source_hash_not_verified_for_this_index"]
        return pending
    required = ("source_model", "source_model_sha256", "dataset", "evidence_path", "evidence_sha256", "cases")
    if any(k not in source for k in required):
        pending["pending_reasons"] = ["source_index_missing_required_evidence"]
        return pending
    if not HASH.fullmatch(source["source_model_sha256"]) or source["dataset"] != "dset3":
        pending["pending_reasons"] = ["source_hash_or_dataset_invalid"]
        return pending
    evidence_path = Path(source["evidence_path"])
    if not evidence_path.is_file() or sha256(evidence_path) != source["evidence_sha256"]:
        pending["pending_reasons"] = ["readback_evidence_missing_or_hash_mismatch"]
        return pending
    # 一个任意文件的SHA不是读回证明：证据内容也必须声明同一源、同一数据集和实际映射。
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pending["pending_reasons"] = ["readback_evidence_is_not_machine_readable"]
        return pending
    if (not isinstance(evidence, dict) or evidence.get("source_hash_verified") is not True
            or any(evidence.get(k) != source[k] for k in ("source_model", "source_model_sha256", "dataset", "source_table_sha256"))):
        pending["pending_reasons"] = ["readback_evidence_source_mismatch"]
        return pending
    matches = [c for c in source["cases"] if c.get("case_id") == record["case_id"]]
    if len(matches) != 1 or matches[0].get("parameter_frequency_readback_verified") is not True:
        pending["pending_reasons"] = ["unique_parameter_frequency_readback_missing"]
        return pending
    case = matches[0]
    evidence_matches = [c for c in evidence.get("cases", []) if isinstance(c, dict) and c.get("case_id") == record["case_id"]]
    fields = ("case_id", "x_scale", "N_w_te1", "N_w_te2", "frequency_Hz", "outer_solnum", "inner_solnum", "parameter_frequency_readback_verified")
    if len(evidence_matches) != 1 or any(evidence_matches[0].get(k) != case.get(k) for k in fields):
        pending["pending_reasons"] = ["readback_evidence_case_mismatch"]
        return pending
    same = all(case.get(k) == record[k] for k in ("x_scale", "N_w_te1", "N_w_te2", "frequency_Hz"))
    indices_ok = all(isinstance(case.get(k), int) and not isinstance(case[k], bool) and case[k] >= 1 for k in ("outer_solnum", "inner_solnum"))
    if not same or not indices_ok:
        pending["pending_reasons"] = ["parameter_frequency_or_index_mismatch"]
        return pending
    return {"outer_solnum": case["outer_solnum"], "inner_solnum": case["inner_solnum"], "export_ready": True,
            "index_status": "verified_index_evidence_for_readonly_export_only", "source_model": source["source_model"],
            "source_model_sha256": source["source_model_sha256"], "source_hash_verified": True,
            "readback_evidence": {"path": str(evidence_path.resolve()), "sha256": source["evidence_sha256"]},
            "pending_reasons": [], "exact_point_consistency_still_required_at_export": True}


def build_sparse_plan(inventory, exposed_case_ids, *, seed=DEFAULT_SEED, source_index=None, source_hints=None):
    records = _validated_records(inventory)
    exposed = set(exposed_case_ids)
    splits = freeze_splits(records, exposed, seed)
    index = _source_index_map(source_index)
    groups = defaultdict(list)
    for record in records.values():
        groups[branch_id(record)].append(record)
    selected, shortages = {}, []
    for bid, members in sorted(groups.items()):
        for cid in sorted(exposed & {r["case_id"] for r in members}):
            require(records[cid]["first_observable_peak_found"], "Exposed pilot has no observable peak")
            selected[cid] = "prior_exposed_development_reuse"
        for split, quota in (("train", 3), ("dev", 1), ("test", 1)):
            existing = sum(splits[cid]["splits"]["parameter_holdout"] == split for cid in selected if splits[cid]["branch_id"] == bid)
            needed = max(0, quota - existing)
            eligible = [r for r in members if r["first_observable_peak_found"] and not r.get("quarantined", False)
                        and splits[r["case_id"]]["splits"]["parameter_holdout"] == split and r["case_id"] not in selected]
            chosen = spaced_x(eligible, needed)
            selected.update({r["case_id"]: "sparse_parameter_space_selection" for r in chosen})
            if len(chosen) < needed:
                shortages.append({"branch_id": bid, "split": split, "requested": needed, "available": len(chosen),
                                  "reason": "insufficient_peak_eligible_designs_do_not_substitute_across_splits"})
    cases = []
    for cid, reason in sorted(selected.items()):
        record = records[cid]
        case = dict(record)
        # 原记录可能来自旧导出清单，必须清空后只用显式证据恢复索引。
        case.update(resolve_indices(record, index))
        case.update(geometry_id=cid, design_id=cid, branch_id=branch_id(record),
                    selection={**splits[cid], "reason": reason},
                    training_eligibility="lineage_quarantine" if record.get("lineage_alignment_pending", False) else "pending_physics_and_field",
                    mode_identity="unverified", training_ready=False, release_allowed=False,
                    resolve_solution_indices=not case["export_ready"])
        cases.append(case)
    registry = []
    for source in inventory["sources"]:
        n2 = source["N_w_te2"]
        registry.append({"N_w_te2": n2, "source_table_sha256": source["sha256"], "source_table_path": source["path"],
                         **(source_hints or {}).get(n2, {}), "source_hash_verified": False,
                         "historical_hints_are_not_current_verification": True,
                         "lineage_alignment_pending": bool(source.get("lineage_alignment_pending", False))})
    plan = {"schema": SCHEMA, "seed": seed, "source_type": "simulation", "dataset": "dset3",
            "field_expression": "acpr.p_t", "observation_xyz_m": [0.0, 0.0, -1e-5],
            "selection_policy": "per_discrete_branch_3train_1dev_1test_spread_in_x_plus_all_exposed_dev",
            "selection_does_not_rank_pressure": True, "split_unit": "complete_geometry_x_scale_N_w_te1_N_w_te2",
            "holdout_caveat": "reserved_field_holdout_not_previously_unseen_scalar_data_or_cross_model_validation",
            "n_inventory_designs": len(records), "n_discrete_branches": len(groups), "n_selected": len(cases),
            "n_previously_exposed": len(exposed), "n_export_ready": sum(c["export_ready"] for c in cases),
            "n_lineage_quarantined": sum(c["training_eligibility"] == "lineage_quarantine" for c in cases),
            "split_counts": {policy: dict(Counter(c["selection"]["splits"][policy] for c in cases)) for policy in ("parameter_holdout", "branch_holdout")},
            "shortages": shortages, "cases": cases,
            "comsol_solve_requested": False, "remote_execution_requested": False,
            "operator_training_status": "not_trained", "training_ready": False, "release_allowed": False}
    frozen = {"schema": "memsharness.pmut_f1_frozen_splits/v0", "seed": seed,
              "policy": "parameter_holdout_and_whole_discrete_branch_holdout", "assignments": list(splits.values()),
              "test_claim": "not_a_blind_scalar_test", "previously_exposed_case_ids": sorted(exposed)}
    pending = {"schema": "memsharness.pmut_f1_source_pending/v0", "sources": registry,
               "pending_case_ids": [c["case_id"] for c in cases if not c["export_ready"]],
               "lineage_quarantine_case_ids": [c["case_id"] for c in cases if c["training_eligibility"] == "lineage_quarantine"],
               "required_next_steps": ["verify_source_bytes", "mphsolutioninfo_parameter_frequency_mapping",
                   "exact_point_complex_readback", "aligned_physics_inputs", "mode_identity_validation"]}
    return plan, frozen, pending


def write_plan_run(output_dir, plan, frozen, pending):
    output_dir = Path(output_dir)
    require(not output_dir.exists(), "Output must be a new run directory")
    output_dir.mkdir(parents=True, exist_ok=False)
    payloads = {"plan.json": plan, "splits.json": frozen, "source_pending.json": pending}
    for name, payload in payloads.items():
        write_new_json(output_dir / name, payload)
    hashes = {name: sha256(output_dir / name) for name in payloads}
    write_new_json(output_dir / "file_hashes.json", hashes)
    return hashes
