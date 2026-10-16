"""几何条件复声压算子研究基线；不是插值/POD 回归，也不是已认证求解器。

数据契约见 ``DATASET_SCHEMA``。每设计一个 NPZ：condition_points[M,F] 只
含几何/材料/边界等已知条件，context[K] 含驱动/频率；query_xyz_m[N,3]
为查询坐标。target_pressure_ri_Pa[N,2]、loss_mask[N] 和精确点真值只
用于监督/评分，绝不进入 branch 编码器。当前实现尚无独立物理证据绑定验收，
因此始终要求显式研究实验；training_ready/release_allowed 恒为 false。

torch 为可选依赖，数据验收/划分/归一化/指标不依赖 torch。PointNet 风格
变长集合编码器加坐标 trunk，直接输出实部与虚部，不使用场 POD 系数。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

DATASET_SCHEMA = "memsharness.pmut_pressure_operator_dataset/v0"
REQUIRED_PHYSICS = ("geometry", "material", "boundary", "excitation", "circuit", "damping", "selection")
SPLITS = ("train", "validation", "test")
SHA = re.compile(r"[0-9a-f]{64}\Z")
FEATURE_UNITS = {
    "x_m": "m", "y_m": "m", "z_m": "m", "normal_x": "1", "normal_y": "1", "normal_z": "1",
    "domain_id": "1", "boundary_id": "1", "material_id": "1", "boundary_type_id": "1",
    "density_kg_m3": "kg/m^3", "sound_speed_m_s": "m/s", "bulk_modulus_Pa": "Pa",
    "young_modulus_Pa": "Pa", "poisson_ratio": "1", "loss_factor": "1", "conductivity_S_m": "S/m",
    "x_scale": "1", "N_w_te1": "1", "N_w_te2": "1", "frequency_Hz": "Hz",
    "drive_voltage_real_V": "V", "drive_voltage_imag_V": "V", "bias_voltage_V": "V",
    "drive_current_real_A": "A", "drive_current_imag_A": "A", "circuit_resistance_ohm": "ohm",
    "circuit_capacitance_F": "F", "circuit_inductance_H": "H", "thickness_m": "m",
}
for _i in range(1, 7):
    for _j in range(1, 7):
        FEATURE_UNITS[f"elastic_c{_i}{_j}_Pa"] = "Pa"
for _i in range(1, 4):
    for _j in range(1, 7):
        FEATURE_UNITS[f"piezoelectric_e{_i}{_j}_C_m2"] = "C/m^2"
    for _j in range(1, 4):
        FEATURE_UNITS[f"permittivity_{_i}{_j}_F_m"] = "F/m"


class OperatorDataError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise OperatorDataError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    def reject(value):
        raise OperatorDataError("Nonfinite JSON constant: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=reject)


def write_new_json(path, payload):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def feature_names(items, label):
    require(isinstance(items, list) and bool(items), label + " must be a nonempty feature list")
    names = []
    for feature in items:
        require(isinstance(feature, dict) and set(feature) == {"name", "unit"}, "Feature needs name/unit only")
        name = feature["name"]
        require(name in FEATURE_UNITS, "Unapproved or solution-derived input feature: " + str(name))
        require(feature["unit"] == FEATURE_UNITS[name], "Incorrect SI unit for " + name)
        require(name not in names, "Duplicate feature: " + name)
        names.append(name)
    return names


@dataclass
class OperatorCase:
    metadata: dict[str, Any]
    condition_points: np.ndarray
    context: np.ndarray
    query_xyz_m: np.ndarray
    target_pressure_ri_Pa: np.ndarray
    loss_mask: np.ndarray
    exact_query_xyz_m: np.ndarray
    exact_pressure_ri_Pa: np.ndarray
    query_weights: np.ndarray | None = None

    @property
    def split(self):
        return self.metadata["split"]


@dataclass
class OperatorDataset:
    manifest: dict[str, Any]
    manifest_sha256: str
    cases: list[OperatorCase]
    blockers: list[str]


def validate_splits(cases, split_policy):
    require(split_policy in ("branch_holdout", "design_holdout", "parameter_holdout"), "Unknown split policy")
    designs, branches, case_ids = {}, {}, set()
    for case in cases:
        meta = case.metadata if isinstance(case, OperatorCase) else case
        for key in ("case_id", "design_id", "branch_id"):
            require(isinstance(meta.get(key), str) and meta[key].strip() == meta[key] and bool(meta[key]), "Missing " + key)
        require(meta["case_id"] not in case_ids, "Duplicate case_id")
        case_ids.add(meta["case_id"])
        require(meta.get("split") in SPLITS, "Only train/validation/test splits are accepted")
        require(meta["design_id"] not in designs, "Duplicate design: single-frequency design must not leak across snapshots/splits")
        designs[meta["design_id"]] = meta["split"]
        old = branches.setdefault(meta["branch_id"], meta["split"])
        if split_policy == "branch_holdout":
            require(old == meta["split"], "Discrete branch leaks across splits: " + meta["branch_id"])
        require(meta.get("lineage_alignment_pending") is not True and meta.get("training_eligibility") != "lineage_quarantine",
                "Quarantined lineage must be excluded from training manifest")
    require(set(designs.values()) == set(SPLITS), "All three complete-design splits are required")


def finite_matrix(value, columns, label):
    a = np.asarray(value)
    require(a.dtype.kind in "iuf" and a.ndim == 2 and a.shape[0] > 0 and a.shape[1] == columns,
            "Invalid shape/type for " + label)
    require(np.isfinite(a).all(), "Nonfinite input: " + label)
    return a.astype(np.float64)


def load_dataset(manifest_path: Path, *, research_only: bool = False) -> OperatorDataset:
    """严格读取白名单输入；缺失真值/条件不补零、不用压力掩膜伪造几何。"""
    require(research_only, "Production training refused: this implementation is research-only; independent physics evidence binding is not implemented")
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path)
    require(manifest.get("schema") == DATASET_SCHEMA, "Unsupported operator dataset schema")
    points = feature_names(manifest.get("condition_features"), "condition_features")
    contexts = feature_names(manifest.get("context_features"), "context_features")
    require(all(name in points for name in ("x_m", "y_m", "z_m")), "Condition geometry needs x/y/z coordinates")
    require("frequency_Hz" in contexts, "Frequency must be an explicit condition")
    require(isinstance(manifest.get("cases"), list), "Missing cases")
    policy = manifest.get("split_policy", "branch_holdout")
    validate_splits(manifest["cases"], policy)
    blockers, cases = {"production_physics_evidence_binding_not_implemented"}, []
    artifact_paths, artifact_hashes = {}, {}
    base = manifest_path.parent
    for meta in manifest["cases"]:
        require(meta.get("source_type") in ("simulation", "synthetic_test"), "Only declared simulation/research fixtures accepted")
        require(isinstance(meta.get("source_model_sha256"), str) and SHA.fullmatch(meta["source_model_sha256"]), "Missing source model SHA256")
        require(meta.get("frequency_source") in ("stored_solution_oracle", "prescribed", "independently_predicted"), "Undeclared frequency source")
        require(meta.get("mode_identity") in ("unverified", "verified_first_mode"), "Unknown mode identity")
        provenance = meta.get("input_provenance")
        require(provenance in ("pre_solve_geometry_and_conditions", "saved_solution_evaluation_geometry", "synthetic_test"), "Input provenance must be explicit")
        require(meta.get("domain_semantics") in ("geometric_domain_ids_verified", "verified_domain_ids", "unverified"), "Domain semantics must be explicit")
        if meta["domain_semantics"] == "unverified":
            blockers.add("domain_to_physics_semantics_unverified")
        if provenance != "pre_solve_geometry_and_conditions":
            blockers.add("inference_geometry_pipeline_unverified")
        if meta["source_type"] == "synthetic_test":
            blockers.add("synthetic_pipeline_test_not_physics_evidence")
        if meta["frequency_source"] == "stored_solution_oracle":
            blockers.add("oracle_frequency_not_end_to_end_frequency_prediction")
        if meta["frequency_source"] == "independently_predicted":
            blockers.add("predicted_frequency_requires_matching_truth_and_separate_frequency_error_validation")
        if meta["mode_identity"] != "verified_first_mode":
            blockers.add("first_observable_peak_only_mode_identity_unverified")
        evidence = meta.get("physics_evidence", {})
        require(isinstance(evidence, dict), "physics_evidence must be an object")
        for kind in REQUIRED_PHYSICS:
            item = evidence.get(kind)
            # true 不是证据；需要独立可追溯 artifact 哈希和逐设计一致性声明。
            if not (isinstance(item, dict) and item.get("verified") is True
                    and item.get("design_id") == meta["design_id"]
                    and isinstance(item.get("artifact_sha256"), str) and SHA.fullmatch(item["artifact_sha256"])):
                blockers.add("missing_verified_physics_" + kind)
        require(isinstance(meta.get("npz"), str), "Missing NPZ path")
        relative = Path(meta["npz"])
        require(not relative.is_absolute() and ".." not in relative.parts, "NPZ must be a safe relative path")
        path = (base / relative).resolve()
        require(path.is_relative_to(base) and path.suffix == ".npz", "NPZ path escapes dataset")
        require(isinstance(meta.get("sha256"), str) and SHA.fullmatch(meta["sha256"]), "Missing NPZ hash")
        require(path.is_file() and sha256(path) == meta["sha256"], "NPZ SHA256 mismatch: " + meta["case_id"])
        for value, seen in ((str(path), artifact_paths), (meta["sha256"], artifact_hashes)):
            require(value not in seen or seen[value] == meta["split"], "Same NPZ path or SHA256 reused across splits under different design aliases")
            seen[value] = meta["split"]
        with np.load(path, allow_pickle=False) as stored:
            required = {"condition_points", "context", "query_xyz_m", "target_pressure_ri_Pa", "loss_mask",
                        "exact_query_xyz_m", "exact_pressure_ri_Pa"}
            require(required <= set(stored.files) and set(stored.files) <= required | {"query_weights"}, "Unexpected/missing NPZ arrays")
            cp = finite_matrix(stored["condition_points"], len(points), "condition_points")
            for j, name in enumerate(points):
                if name.endswith("_id"):
                    require(np.equal(cp[:, j], np.floor(cp[:, j])).all() and (cp[:, j] >= 0).all(), "Noninteger geometric ID")
            context = np.asarray(stored["context"])
            require(context.shape == (len(contexts),) and context.dtype.kind in "iuf" and np.isfinite(context).all(), "Invalid context")
            require(context[contexts.index("frequency_Hz")] > 0, "Nonpositive frequency")
            q = finite_matrix(stored["query_xyz_m"], 3, "query_xyz_m")
            target = np.asarray(stored["target_pressure_ri_Pa"])
            require(target.shape == (len(q), 2) and target.dtype.kind in "iuf", "Pressure needs explicit real/imag columns")
            mask = np.asarray(stored["loss_mask"])
            require(mask.shape == (len(q),) and mask.dtype.kind == "b" and mask.any(), "Loss mask must be nonempty boolean vector")
            require(np.isfinite(target[mask]).all(), "Nonfinite supervised pressure")
            exact_q = finite_matrix(stored["exact_query_xyz_m"], 3, "exact_query_xyz_m")
            exact_p = finite_matrix(stored["exact_pressure_ri_Pa"], 2, "exact_pressure_ri_Pa")
            require(exact_q.shape == (1, 3) and exact_p.shape == (1, 2), "One exact observation required")
            require(np.allclose(exact_q[0], [0, 0, -1e-5], rtol=0, atol=1e-15), "Observation must be the below 10um point")
            weights = None
            if "query_weights" in stored.files:
                weights = np.asarray(stored["query_weights"])
                require(weights.shape == (len(q),) and weights.dtype.kind in "iuf" and np.isfinite(weights).all()
                        and (weights >= 0).all() and weights[mask].sum() > 0, "Invalid quadrature weights")
                require(meta.get("query_weights_provenance") == "verified_physical_quadrature", "Weights need quadrature provenance")
                weights = weights.astype(float)
            cases.append(OperatorCase(dict(meta), cp, context.astype(float), q, target.astype(float),
                                      mask.copy(), exact_q, exact_p, weights))
    return OperatorDataset(manifest, sha256(manifest_path), cases, sorted(blockers))


def _balanced_moments(arrays):
    # 每个设计权重相同；网格更密的设计不主导归一化统计。
    mean = np.mean([a.mean(axis=0) for a in arrays], axis=0)
    variance = np.mean([np.mean((a - mean) ** 2, axis=0) for a in arrays], axis=0)
    return mean, np.where(variance > 0, np.sqrt(variance), 1.0)


def supervision_indices(case):
    """精确观测点另作评估：即使场网格恰好命中该坐标，也不将其加入训练。"""
    exact = np.all(np.isclose(case.query_xyz_m, case.exact_query_xyz_m[0], rtol=0, atol=1e-15), axis=1)
    valid = case.loss_mask & ~exact
    if case.query_weights is not None:
        valid = valid & (case.query_weights > 0)
    selected = np.flatnonzero(valid)
    require(len(selected) > 0, "No field supervision remains after excluding the exact observation")
    return selected


@dataclass
class TrainNormalization:
    condition_mean: np.ndarray
    condition_scale: np.ndarray
    context_mean: np.ndarray
    context_scale: np.ndarray
    query_mean: np.ndarray
    query_scale: np.ndarray
    pressure_scale_Pa: float
    fitted_design_ids: list[str]

    @classmethod
    def fit(cls, cases):
        train = [c for c in cases if c.split == "train"]
        require(bool(train), "No train designs")
        cm, cs = _balanced_moments([c.condition_points for c in train])
        xm, xs = _balanced_moments([c.context[None, :] for c in train])
        qm, qs = _balanced_moments([c.query_xyz_m for c in train])
        pscale = math.sqrt(float(np.mean([np.mean(np.sum(c.target_pressure_ri_Pa[supervision_indices(c)] ** 2, axis=1)) for c in train])))
        require(math.isfinite(pscale) and pscale > 0, "Training pressure scale is zero/nonfinite")
        return cls(cm, cs, xm, xs, qm, qs, pscale, sorted(c.metadata["design_id"] for c in train))

    def to_dict(self):
        return {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in asdict(self).items()}


def complex_metrics(prediction, truth, mask=None, weights=None):
    """复数相对 L2；无积分权重时明确为点集范数，不伪称体积分误差界。"""
    pred, target = np.asarray(prediction, dtype=float), np.asarray(truth, dtype=float)
    require(pred.shape == target.shape and pred.ndim == 2 and pred.shape[1] == 2, "Metrics require N x 2 real/imag arrays")
    valid = np.ones(len(target), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    require(valid.shape == (len(target),) and valid.any(), "Empty/misaligned metric mask")
    require(np.isfinite(pred[valid]).all() and np.isfinite(target[valid]).all(), "Nonfinite metric values")
    w = np.ones(int(valid.sum())) if weights is None else np.asarray(weights, dtype=float)[valid]
    require(np.isfinite(w).all() and (w >= 0).all() and w.sum() > 0, "Invalid metric weights")
    error_sq = np.sum((pred[valid] - target[valid]) ** 2, axis=1)
    truth_sq = np.sum(target[valid] ** 2, axis=1)
    denominator = float(np.sum(w * truth_sq))
    absolute_rms = math.sqrt(float(np.sum(w * error_sq) / w.sum()))
    return {
        "relative_complex_l2": math.sqrt(float(np.sum(w * error_sq)) / denominator) if denominator > 0 else None,
        "complex_rmse_Pa": absolute_rms, "zero_truth_norm": denominator == 0,
        "norm_definition": "physical_quadrature_relative_complex_l2" if weights is not None else "pointwise_relative_complex_l2",
        "n_valid_points": int(valid.sum()),
    }


def exact_point_metrics(prediction, truth):
    out = complex_metrics(prediction, truth)
    p, t = complex(*np.asarray(prediction).reshape(2)), complex(*np.asarray(truth).reshape(2))
    out.update({"amplitude_absolute_error_Pa": abs(abs(p) - abs(t)),
                "amplitude_relative_error": abs(abs(p) - abs(t)) / abs(t) if abs(t) > 0 else None,
                "phase_absolute_error_rad": abs(float(np.angle(p * t.conjugate()))) if abs(p) > 0 and abs(t) > 0 else None})
    return out


def dataset_audit(dataset):
    return {
        "schema": "memsharness.pmut_pressure_operator_audit/v0", "manifest_sha256": dataset.manifest_sha256,
        "n_designs": len(dataset.cases), "designs_by_split": {s: sum(c.split == s for c in dataset.cases) for s in SPLITS},
        "split_policy": dataset.manifest.get("split_policy", "branch_holdout"),
        "source_types": sorted({c.metadata["source_type"] for c in dataset.cases}),
        "frequency_sources": sorted({c.metadata["frequency_source"] for c in dataset.cases}),
        "mode_label": "first_observable_peak_research" if any(c.metadata["mode_identity"] != "verified_first_mode" for c in dataset.cases) else "declared_first_mode_requires_independent_review",
        "blockers": dataset.blockers, "torch_available": importlib.util.find_spec("torch") is not None,
        "training_ready": False, "release_allowed": False, "cross_model_transfer_verified": False,
        "field_error_bound_verified": False, "solver_status": "research_only_not_certified",
        "limitations": ["No physical certification, mesh convergence, calibrated error bounds or optimal-design claim.",
                        "Saved-solution geometry does not demonstrate an inference-time geometry pipeline.",
                        "Oracle-frequency field metrics are not end-to-end first-mode frequency/field prediction.",
                        "Physical metadata declarations require independent artifact/selection verification."],
    }


def build_model(condition_dim, context_dim, *, width=64, latent=32):
    """变长点集合的共享编码 + 坐标 trunk；不读取任何压力/位移标签。"""
    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise RuntimeError("Optional torch dependency missing; audit-only works without it. Install in an isolated research environment.") from exc
    require(min(condition_dim, context_dim, width, latent) > 0, "Invalid network dimensions")

    class PointConditionedPressureOperator(nn.Module):
        def __init__(self):
            super().__init__()
            self.point_encoder = nn.Sequential(nn.Linear(condition_dim, width), nn.Tanh(), nn.Linear(width, width), nn.Tanh())
            self.branch = nn.Sequential(nn.Linear(2 * width + context_dim, width), nn.Tanh(), nn.Linear(width, 2 * latent))
            self.trunk = nn.Sequential(nn.Linear(3, width), nn.Tanh(), nn.Linear(width, latent))
            self.bias = nn.Parameter(torch.zeros(2))

        def encode(self, condition_points, context):
            if condition_points.ndim != 2 or context.ndim != 1 or len(condition_points) == 0:
                raise ValueError("One unpadded variable-length design point set and context required")
            encoded = self.point_encoder(condition_points)
            pooled = torch.cat((encoded.mean(dim=0), encoded.max(dim=0).values, context), dim=0)
            return self.branch(pooled).reshape(2, latent)

        def decode(self, encoded, query_xyz):
            return self.trunk(query_xyz) @ encoded.T / math.sqrt(latent) + self.bias

        def forward(self, condition_points, context, query_xyz):
            return self.decode(self.encode(condition_points, context), query_xyz)

    return PointConditionedPressureOperator()


def _case_inputs(case, normalizer):
    # 白名单构造，绝不把 labels/mask/exact_pressure 拼进输入。
    return ((case.condition_points - normalizer.condition_mean) / normalizer.condition_scale,
            (case.context - normalizer.context_mean) / normalizer.context_scale)


def train_operator(dataset, output_dir, *, research_only=False, epochs=100, width=64, latent=32,
                   query_points_per_design=2048, max_condition_points=4096, learning_rate=1e-3,
                   seed=0, max_seconds=600.0, device="cpu", torch_threads=1):
    require(research_only, "Production training refused: this implementation supports research-only experiments")
    require(isinstance(epochs, int) and 1 <= epochs <= 10000, "Invalid epoch budget")
    require(query_points_per_design > 0 and max_condition_points > 0 and max_seconds > 0, "Invalid training resource budget")
    require(math.isfinite(learning_rate) and learning_rate > 0, "Invalid learning rate")
    require(isinstance(torch_threads, int) and 1 <= torch_threads <= 64, "Invalid CPU thread budget")
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Optional torch dependency missing; use --audit-only or an isolated torch environment.") from exc
    torch.set_num_threads(torch_threads)
    output_dir = Path(output_dir)
    require(not output_dir.exists(), "Output directory must be new (append-only)")
    normalizer = TrainNormalization.fit(dataset.cases)
    # 初始化也必须在固定种子之后进行。
    torch.manual_seed(seed)
    model = build_model(len(dataset.manifest["condition_features"]), len(dataset.manifest["context_features"]), width=width, latent=latent).to(device)
    rng = np.random.default_rng(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    train = [c for c in dataset.cases if c.split == "train"]
    validation = [c for c in dataset.cases if c.split == "validation"]
    start, history, best, best_state = time.monotonic(), [], math.inf, None
    completed_epochs, timed_out = 0, False

    def tensor(value):
        return torch.as_tensor(value, dtype=torch.float32, device=device)

    def fixed_inputs(case):
        points, context = _case_inputs(case, normalizer)
        if len(points) > max_condition_points:
            # 与目标值、掩膜无关的可复现下采样；所有split采用同一策略。
            case_seed = seed + int(hashlib.sha256(case.metadata["case_id"].encode()).hexdigest()[:8], 16)
            selected = np.random.default_rng(case_seed).choice(len(points), max_condition_points, replace=False)
            points = points[selected]
        return tensor(points), tensor(context)

    def predict(case, xyz):
        points, context = fixed_inputs(case)
        with torch.no_grad():
            encoded = model.encode(points, context)
            chunks = []
            for offset in range(0, len(xyz), query_points_per_design):
                query = (xyz[offset:offset + query_points_per_design] - normalizer.query_mean) / normalizer.query_scale
                chunks.append(model.decode(encoded, tensor(query)).cpu().numpy() * normalizer.pressure_scale_Pa)
        return np.concatenate(chunks)

    for epoch in range(epochs):
        if time.monotonic() - start > max_seconds:
            timed_out = True
            break
        model.train()
        losses = []
        for index in rng.permutation(len(train)):
            case = train[index]
            selected = supervision_indices(case)
            supervised = selected
            if len(selected) > query_points_per_design:
                selected = rng.choice(selected, query_points_per_design, replace=False)
            points, context = fixed_inputs(case)
            q = tensor((case.query_xyz_m[selected] - normalizer.query_mean) / normalizer.query_scale)
            truth = tensor(case.target_pressure_ri_Pa[selected] / normalizer.pressure_scale_Pa)
            pred = model(points, context, q)
            # 每设计一次优化、各设计相同权重；目标能量仅作loss尺度，不是条件。
            energy_values = np.sum((case.target_pressure_ri_Pa[supervised] / normalizer.pressure_scale_Pa) ** 2, axis=1)
            energy_weights = None if case.query_weights is None else case.query_weights[supervised]
            energy = float(np.average(energy_values, weights=energy_weights))
            weights = tensor(np.ones(len(selected)) if case.query_weights is None else case.query_weights[selected])
            require(float(weights.sum()) > 0, "Sampled quadrature weights all zero")
            loss = (weights * torch.sum((pred - truth) ** 2, dim=1)).sum() / weights.sum() / max(energy, 1e-12)
            require(bool(torch.isfinite(loss)), "Nonfinite training loss")
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        model.eval()
        vals = []
        for case in validation:
            metrics = complex_metrics(predict(case, case.query_xyz_m), case.target_pressure_ri_Pa, case.loss_mask, case.query_weights)
            require(metrics["relative_complex_l2"] is not None, "Zero-norm validation target cannot select checkpoint")
            vals.append(metrics["relative_complex_l2"])
        score = float(np.mean(vals))
        history.append({"epoch": epoch + 1, "mean_design_relative_training_mse": float(np.mean(losses)), "validation_mean_design_relative_complex_l2": score})
        completed_epochs = epoch + 1
        if score < best:
            best, best_state = score, {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    require(best_state is not None, "Budget expired before a validated checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    records = []
    frequency_index = feature_names(dataset.manifest["context_features"], "context_features").index("frequency_Hz")
    for case in dataset.cases:
        record = {key: case.metadata[key] for key in ("case_id", "design_id", "branch_id", "split", "frequency_source", "mode_identity")}
        record["conditioning_frequency_Hz"] = float(case.context[frequency_index])
        record.update(field=complex_metrics(predict(case, case.query_xyz_m), case.target_pressure_ri_Pa, case.loss_mask, case.query_weights),
                      exact_point=exact_point_metrics(predict(case, case.exact_query_xyz_m), case.exact_pressure_ri_Pa))
        records.append(record)
    report = dataset_audit(dataset)
    report.update(schema="memsharness.pmut_pressure_operator_experiment/v0", experiment_only=True,
                  architecture="variable_pointset_mean_max_branch_coordinate_trunk_complex_pressure", interpolation=False,
                  pod_coefficients=False, prediction_source_type="ai_solver", epochs_completed=completed_epochs,
                  time_budget_reached=timed_out, elapsed_seconds=time.monotonic() - start, seed=seed, torch_version=torch.__version__,
                  device=device, torch_threads=torch_threads, design_balanced_training=True, checkpoint_selected_on="validation_only",
                  exact_point_used_for_training=False, field_training_excludes_exact_observation_coordinate=True,
                  normalization_fitted_on="train_only", frequency_prediction_validated=False, history=history, cases=records,
                  condition_features=dataset.manifest["condition_features"], context_features=dataset.manifest["context_features"],
                  training_budget_scope="checked_before_each_epoch_not_a_hard_process_timeout")
    report["metrics_by_split"] = {}
    for split in SPLITS:
        group = [r for r in records if r["split"] == split]
        field = [r["field"]["relative_complex_l2"] for r in group if r["field"]["relative_complex_l2"] is not None]
        point = [r["exact_point"]["relative_complex_l2"] for r in group if r["exact_point"]["relative_complex_l2"] is not None]
        report["metrics_by_split"][split] = {"n_designs": len(group), "field_mean_design_relative_complex_l2": float(np.mean(field)) if field else None,
            "field_max_design_relative_complex_l2": float(np.max(field)) if field else None,
            "exact_point_mean_design_relative_complex_l2": float(np.mean(point)) if point else None,
            "zero_norm_field_cases": len(group) - len(field), "zero_norm_exact_point_cases": len(group) - len(point)}
    output_dir.mkdir(parents=True, exist_ok=False)
    torch.save({"state_dict": best_state, "architecture": {"condition_dim": len(dataset.manifest["condition_features"]),
                "context_dim": len(dataset.manifest["context_features"]), "width": width, "latent": latent},
                "normalization": normalizer.to_dict(), "manifest_sha256": dataset.manifest_sha256,
                "training_ready": False, "release_allowed": False}, output_dir / "research_checkpoint.pt")
    report["checkpoint_sha256"] = sha256(output_dir / "research_checkpoint.pt")
    write_new_json(output_dir / "normalization.json", normalizer.to_dict())
    write_new_json(output_dir / "experiment_report.json", report)
    return report
