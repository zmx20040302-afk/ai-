"""模型接入（onboard）：把任意 COMSOL 模型安全接进平台，产出可用的接入报告与 device_spec 草稿。

对应 `WORKING_PLAN.md` §4.8 的八步 SOP：

| 步 | 内容 | 本模块 |
|---|---|---|
| 1 | 只读复制到 `work/devices/<name>/`，原文件置为只读引用 | ✅ 自动 |
| 2 | 读参数 / 几何 / 物理场 / 研究清单 | ✅ 自动 |
| 3 | **参数审计**：逐个微扰，判定是否影响几何、是否影响选择集、能否求解 → **可安全自动改参白名单** | ✅ 自动 |
| 4 | **选择集完整性检查**（几何变了边界编号可能变，物理场会静默绑错） | ✅ 自动 |
| 5 | 基线求解 + 目标量导出通路验证 | ✅ 自动 |
| 6 | **目标口径确认** | ⏳ 产出待人工确认的草稿（口径差异常达几个百分点） |
| 7 | 登记 `device_spec` | ✅ 产出草稿 YAML |
| 8 | **公共点集与掩膜策略**（场级/POD 必需，依据 P1 实测） | ✅ 自动 |

设计红线（AGENTS.md）：**只操作运行区副本**，绝不改写生产模型；读不到的信息写 null 并记原因，**不猜测**。

用法（**必须经 ASCII 交汇点启动**，否则 JPype 因中文路径报 UnsatisfiedLinkError）：

    C:\\Users\\18161\\memsharness_work\\repo\\work\\.venv\\Scripts\\python.exe -u ^
      C:\\Users\\18161\\memsharness_work\\repo\\scripts\\onboard_model.py ^
      --model "D:\\path\\to\\model.mph" --device pmut-3d --targets "abs(p)"
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import work_root

COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")

# 参数表达式形如 "4[m]" / "1.225[kg/m^3]" / "343[m/s]"；派生表达式（含其它参数名或运算符）不参与自动改参
_NUMERIC_PARAM = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(\[[^\]]*\])?\s*$")

# 判定阈值（相对量）
GEOMETRY_TOL = 1e-6   # 包围盒相对偏移超过此值 → 参数影响几何
EFFECT_TOL = 1e-6     # 目标量相对变化超过此值 → 参数对目标有可测影响（低于此视为数值噪声）
# 默认尝试的目标量表达式（用户可用 --targets 覆盖）
DEFAULT_TARGET_CANDIDATES = ("abs(p)", "p", "T", "u", "w", "V", "abs(u)")


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def parse_numeric(expression: str) -> tuple[float, str] | None:
    """把 "4[m]" 解析成 (4.0, "[m]")；派生表达式返回 None。"""
    match = _NUMERIC_PARAM.match(expression or "")
    if not match:
        return None
    return float(match.group(1)), (match.group(2) or "")


def stage_model(source: Path, device_name: str) -> dict:
    """第 1 步：把模型复制到运行区（只读引用原件），并记录双方哈希。

    副本名冲突时自动递增（`input.mph` → `input_2.mph`）：
    上一次接入的副本可能仍被 mphserver 持有文件锁（实测会报 WinError 32），
    因此**绝不覆盖已有副本**——这也天然保留了历次接入的证据。
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"模型文件不存在：{source}")
    device_dir = work_root() / "devices" / device_name
    device_dir.mkdir(parents=True, exist_ok=True)

    staged = device_dir / source.name
    counter = 1
    while staged.exists():
        try:  # 能删掉说明没被占用；被占用则换名，保留旧副本
            staged.unlink()
            break
        except OSError:
            counter += 1
            staged = device_dir / f"{source.stem}_{counter}{source.suffix}"

    shutil.copy2(source, staged)
    info = {
        "device_name": device_name,
        "source": str(source),
        "source_sha256": sha256_of(source),
        "staged": str(staged),
        "staged_sha256": sha256_of(staged),
        "copy_index": counter,
        "source_lock_present": source.with_suffix(source.suffix + ".lock").exists(),
        "staged_at": datetime.now().isoformat(timespec="seconds"),
        "note": "原文件只读引用；所有改动只作用于本副本；副本按次递增保留作为接入历史",
    }
    return info


# ---------------------------------------------------------------- 设备信息（第 2 步）


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def eval_vector(model, expression: str) -> list[float] | None:
    """安全求值一个表达式，返回一维浮点列表。

    ⚠️ 实测坑：MPh 的 ``model.evaluate()`` 返回的是**数组的列表**（对单个表达式也是 ``[array(...)]``），
    直接按标量迭代会抛 ``TypeError``。必须先用 numpy 展平；复数结果先取模。
    """
    try:
        import numpy as np

        raw = model.evaluate(expression)
        arr = np.asarray(raw)
        if np.iscomplexobj(arr):
            arr = np.abs(arr)
        flat = np.asarray(arr, dtype=float).ravel()
        return [float(v) for v in flat]
    except Exception:
        return None


def inspect_device(model, java) -> dict:
    """第 2 步：读参数、组件、几何维度、网格、物理场、研究。读不到写 null 并记原因。"""
    info: dict[str, Any] = {"components": [], "parameters": {}, "physics": [], "studies": [], "errors": []}
    try:
        comp_tags = [str(t) for t in java.modelNode().tags()]
    except Exception as exc:
        info["errors"].append(f"列组件失败: {type(exc).__name__}: {exc}")
        comp_tags = []
    info["components"] = comp_tags

    for comp_tag in comp_tags:
        comp = java.modelNode(comp_tag)
        geom_tags = _safe(lambda: [str(t) for t in comp.geom().tags()], [])
        mesh_tags = _safe(lambda: [str(t) for t in comp.mesh().tags()], [])
        entry: dict[str, Any] = {"geom": geom_tags, "mesh": mesh_tags, "space_dim": None, "entity_counts": None}
        for geom_tag in geom_tags[:1]:
            seq = comp.geom(geom_tag)
            entry["space_dim"] = _safe(lambda s=seq: int(s.getSDim()))
            entry["entity_counts"] = {
                key: _safe(lambda s=seq, k=key: int(getattr(s, k)()))
                for key in ("getNVertices", "getNEdges", "getNBoundaries", "getNDomains")
            }
        info.setdefault("geometry", {})[comp_tag] = entry

        physics_list = []
        phys_tags = _safe(lambda c=comp: [str(t) for t in c.physics().tags()], [])
        for phys_tag in phys_tags:
            phys = comp.physics(phys_tag)
            physics_list.append({
                "tag": phys_tag,
                "type": _safe(lambda p=phys: str(p.getType())),
                "selection_count": _safe(lambda p=phys: int(p.selection().entities().length)),
            })
        info["physics"].extend(physics_list)

    try:
        info["parameters"] = {str(k): str(v) for k, v in model.parameters().items()}
    except Exception as exc:
        info["errors"].append(f"读参数失败: {type(exc).__name__}: {exc}")
    info["studies"] = _safe(lambda: [str(s) for s in model.studies()], [])
    return info


# ---------------------------------------------------------------- 测量与审计（第 3、4 步）


def measure(model, java, comp_tag: str, geom_tag: str) -> dict:
    """测量一次状态：包围盒、节点数、几何实体数、物理场选择集计数。

    包围盒由**节点坐标**求得（比实体计数更能反映几何变化：矩形改尺寸时实体数不变）。
    """
    xs = eval_vector(model, "x")
    ys = eval_vector(model, "y")
    zs = eval_vector(model, "z")          # 2D 模型上会失败 → None，属正常
    comp = java.modelNode(comp_tag)
    geom = comp.geom(geom_tag) if geom_tag else None

    def bbox(values):
        if not values:
            return None
        return [min(values), max(values)]

    selection_counts = {}
    phys_tags = _safe(lambda: [str(t) for t in comp.physics().tags()], [])
    for tag in phys_tags:
        selection_counts[tag] = _safe(lambda t=tag: int(comp.physics(t).selection().entities().length))

    return {
        "bbox": {"x": bbox(xs), "y": bbox(ys), "z": bbox(zs)} if xs else None,
        "n_nodes": len(xs) if xs else None,
        "entity_counts": {
            key: _safe(lambda s=geom, k=key: int(getattr(s, k)()))
            for key in ("getNVertices", "getNEdges", "getNBoundaries", "getNDomains")
        } if geom is not None else None,
        "selection_counts": selection_counts,
    }


def _bbox_shift(a: dict | None, b: dict | None) -> float | None:
    """两个状态的包围盒最大相对偏移（判定参数是否影响几何）。"""
    if not a or not b or not a.get("bbox") or not b.get("bbox"):
        return None
    worst = 0.0
    for axis in ("x", "y", "z"):
        lo_a, hi_a = a["bbox"][axis] or (None, None)
        lo_b, hi_b = b["bbox"][axis] or (None, None)
        if lo_a is None or lo_b is None:
            continue
        span = max(abs(hi_a - lo_a), 1e-12)
        worst = max(worst, abs(lo_b - lo_a) / span, abs(hi_b - hi_a) / span)
    return worst


def relative_shift(base: dict[str, float] | None, now: dict[str, float] | None) -> float | None:
    """目标量相对变化（判定参数是否有效）。"""
    if not base or not now:
        return None
    worst = 0.0
    for key, value in now.items():
        if key not in base or base[key] is None or value is None:
            continue
        scale = max(abs(base[key]), 1e-30)
        worst = max(worst, abs(value - base[key]) / scale)
    return worst


def probe_targets(model, candidates: tuple[str, ...]) -> tuple[dict[str, float], list[str]]:
    """找出真正可求值的目标量表达式（第 5 步的一半）。取各表达式的最大幅值作为标量摘要。"""
    values: dict[str, float] = {}
    failures: list[str] = []
    for expr in candidates:
        flat = eval_vector(model, expr)
        if not flat:
            failures.append(f"{expr}: 求值为空或不可求值")
            continue
        finite = [abs(v) for v in flat if v == v and abs(v) != float("inf")]
        if finite:
            values[expr] = max(finite)
        else:
            failures.append(f"{expr}: 无非有限值")
    return values, failures


def classify_parameter(
    *,
    geometry_rebuilt: bool,
    solve_ok: bool | None,
    selection_intact: bool,
    topology_intact: bool,
    bbox_shift: float | None,
    target_shift: float | None,
) -> str:
    """参数分类（纯函数，便于回归测试）。顺序即优先级。

    - ``broken``：几何/网格重建就失败
    - ``solve_failed``：重建成功但求解失败
    - ``selection_risk``：选择集或拓扑计数变化（几何变了但物理场可能静默绑错）
    - ``geometry``：包围盒偏移超阈值 → 影响几何
    - ``unknown_no_target``：没有任何可用目标量，无法判定有效性（**不冒充无效**）
    - ``material_or_load``：几何不变但目标量有可测变化
    - ``no_measured_effect``：几何不变且目标量变化低于噪声阈值（≠ 物理上无效）
    """
    if not geometry_rebuilt:
        return "broken"
    if solve_ok is False:
        return "solve_failed"
    if not (selection_intact and topology_intact):
        return "selection_risk"
    if bbox_shift is not None and bbox_shift > GEOMETRY_TOL:
        return "geometry"
    if target_shift is None:
        return "unknown_no_target"
    if target_shift > EFFECT_TOL:
        return "material_or_load"
    return "no_measured_effect"


def audit_parameters(
    model,
    java,
    study: str,
    comp_tag: str,
    geom_tag: str,
    mesh_tag: str,
    targets: dict[str, float],
    *,
    delta: float = 0.05,
    max_params: int = 12,
    do_solve: bool = True,
    log=print,
) -> dict:
    """第 3、4 步：逐个参数微扰，产出**可安全自动改参白名单**及其实测证据。"""
    geom = java.modelNode(comp_tag).geom(geom_tag)
    mesh = java.modelNode(comp_tag).mesh(mesh_tag)
    params = {str(k): str(v) for k, v in model.parameters().items()}

    # ★ 归一化基线：先重建几何+网格并重解一次，再测基线。
    #   否则基线测的是 .mph 里保存的网格，而微扰后测的是重建网格，节点数天然不同，
    #   会把材质参数误判成几何参数（本模块首次实现即踩到此坑）。
    try:
        geom.run()
        mesh.run()
        if do_solve:
            model.solve(study)
        log("[audit] 已归一化基线状态（重建几何+网格后测量）")
    except Exception as exc:
        log(f"[audit] ⚠️ 基线归一化失败（将按现有状态测量）: {type(exc).__name__}: {str(exc)[:120]}")

    baseline_measure = measure(model, java, comp_tag, geom_tag)
    baseline_targets = targets

    results: list[dict] = []
    skipped: list[dict] = []
    audit_started = time.perf_counter()

    for name, expression in list(params.items()):
        parsed = parse_numeric(expression)
        if parsed is None:
            skipped.append({"name": name, "value": expression,
                            "reason": "派生表达式（含其它参数或运算），不参与自动改参"})
            continue
        if len(results) >= max_params:
            skipped.append({"name": name, "value": expression, "reason": f"超过本次审计上限 {max_params}"})
            continue

        original_value, unit = parsed
        perturbed = original_value * (1.0 + delta)
        entry: dict[str, Any] = {
            "name": name, "original": expression, "perturbed": f"{perturbed:g}{unit}",
            "delta_fraction": delta,
        }
        log(f"[audit] 微扰 {name}: {expression} → {entry['perturbed']}")
        try:
            java.param().set(name, entry["perturbed"])
            geom.run()
            mesh.run()
            entry["geometry_rebuilt"] = True
        except Exception as exc:
            entry["geometry_rebuilt"] = False
            entry["error"] = f"几何/网格重建失败: {type(exc).__name__}: {str(exc)[:160]}"

        solve_ok = None
        solve_seconds = None
        if do_solve and entry.get("geometry_rebuilt"):
            t0 = time.perf_counter()
            try:
                model.solve(study)
                solve_ok = True
            except Exception as exc:
                solve_ok = False
                entry["solve_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            solve_seconds = round(time.perf_counter() - t0, 2)

        entry["solve_ok"] = solve_ok
        entry["solve_seconds"] = solve_seconds
        state = measure(model, java, comp_tag, geom_tag)
        entry["bbox_relative_shift"] = _bbox_shift(baseline_measure, state)
        entry["n_nodes_before"] = baseline_measure.get("n_nodes")
        entry["n_nodes_after"] = state.get("n_nodes")
        entry["entity_counts_after"] = state.get("entity_counts")
        entry["selection_counts_after"] = state.get("selection_counts")
        entry["selection_counts_baseline"] = baseline_measure.get("selection_counts")
        entry["selection_intact"] = (
            state.get("selection_counts") == baseline_measure.get("selection_counts")
        )
        entry["topology_intact"] = (
            state.get("entity_counts") == baseline_measure.get("entity_counts")
        )
        new_targets, _ = probe_targets(model, tuple(baseline_targets.keys())) if solve_ok else ({}, [])
        entry["targets_after"] = new_targets
        entry["target_relative_shift"] = relative_shift(baseline_targets, new_targets)

        # ---- 分类（纯函数 classify_parameter，阈值见 GEOMETRY_TOL / EFFECT_TOL）----
        classification = classify_parameter(
            geometry_rebuilt=bool(entry.get("geometry_rebuilt")),
            solve_ok=solve_ok,
            selection_intact=bool(entry["selection_intact"]),
            topology_intact=bool(entry["topology_intact"]),
            bbox_shift=entry["bbox_relative_shift"],
            target_shift=entry["target_relative_shift"],
        )
        entry["classification"] = classification
        entry["whitelist_ok"] = classification in ("geometry", "material_or_load")
        results.append(entry)
        log(f"[audit]   → {classification}（几何偏移={entry['bbox_relative_shift']}，"
            f"选择集完整={entry['selection_intact']}，拓扑完整={entry['topology_intact']}，"
            f"目标变化={entry['target_relative_shift']}）")

        # ---- 复位 ----
        try:
            java.param().set(name, expression)
            geom.run()
            mesh.run()
            if do_solve:
                model.solve(study)
        except Exception as exc:
            skipped.append({"name": name, "reason": f"复位失败，审计提前结束: {type(exc).__name__}: {str(exc)[:120]}"})
            break

    whitelist = [
        {
            "name": item["name"],
            "original": item["original"],
            "classification": item["classification"],
            "evidence": {
                "bbox_relative_shift": item["bbox_relative_shift"],
                "selection_intact": item["selection_intact"],
                "target_relative_shift": item["target_relative_shift"],
                "solve_seconds": item["solve_seconds"],
            },
        }
        for item in results if item.get("whitelist_ok")
    ]
    return {
        "delta_fraction": delta,
        "max_params": max_params,
        "do_solve": do_solve,
        "thresholds": {"geometry_tol": GEOMETRY_TOL, "effect_tol": EFFECT_TOL},
        "audit_seconds": round(time.perf_counter() - audit_started, 1),
        "baseline": baseline_measure,
        "results": results,
        "skipped": skipped,
        "whitelist": whitelist,
        "note": "白名单仅代表『可安全自动改参』；参数取值范围仍需任务合同给出（本模块不猜范围）",
    }


# ---------------------------------------------------------------- 公共点集（第 8 步）


def define_public_point_set(measure_state: dict, nx: int = 31, ny: int = 23, nz: int = 0) -> dict:
    """第 8 步：依据基线包围盒定义**固定公共点集**（紧凑规格，不展开坐标数组）。

    依据 P1 实测（WORKING_PLAN §4.4B）：几何变化会导致域外点变 NaN，必须掩膜。
    显式坐标点写入 `pod_points.txt`，本结构只保存规格，避免 device_spec 被上千个浮点数淹没。
    """
    bbox = (measure_state or {}).get("bbox") or {}
    axes: dict[str, dict[str, float | int]] = {}
    grid_points = 1
    for axis, n in (("x", nx), ("y", ny), ("z", nz)):
        span = bbox.get(axis)
        if not span or n <= 0:
            continue
        lo, hi = float(span[0]), float(span[1])
        axes[axis] = {"start": lo, "stop": hi, "n": int(n)}
        grid_points *= int(n)
    return {
        "axes": axes,
        "grid_points": grid_points,
        "bbox": bbox,
        "points_file": "pod_points.txt",
        "mask_policy": "域外点记 NaN；POD 与误差统计只在掩膜点集上进行（依据 P1 实测）",
    }


def write_public_points(device_dir: Path, spec: dict) -> str | None:
    """把公共点集的显式坐标写入 `pod_points.txt`（每行一列坐标，与 spec.axes 顺序一致）。"""
    axes = spec.get("axes") or {}
    if not axes:
        return None
    order = [a for a in ("x", "y", "z") if a in axes]
    lines: list[str] = []
    if len(order) == 2:
        ax, ay = (axes[order[0]], axes[order[1]])
        for iy in range(int(ay["n"])):
            y = ay["start"] + (ay["stop"] - ay["start"]) * iy / max(1, int(ay["n"]) - 1)
            for ix in range(int(ax["n"])):
                x = ax["start"] + (ax["stop"] - ax["start"]) * ix / max(1, int(ax["n"]) - 1)
                lines.append(f"{x:.10g} {y:.10g}")
    elif len(order) == 3:
        ax, ay, az = (axes[order[0]], axes[order[1]], axes[order[2]])
        for iz in range(int(az["n"])):
            z = az["start"] + (az["stop"] - az["start"]) * iz / max(1, int(az["n"]) - 1)
            for iy in range(int(ay["n"])):
                y = ay["start"] + (ay["stop"] - ay["start"]) * iy / max(1, int(ay["n"]) - 1)
                for ix in range(int(ax["n"])):
                    x = ax["start"] + (ax["stop"] - ax["start"]) * ix / max(1, int(ax["n"]) - 1)
                    lines.append(f"{x:.10g} {y:.10g} {z:.10g}")
    else:
        ax = axes[order[0]]
        for ix in range(int(ax["n"])):
            x = ax["start"] + (ax["stop"] - ax["start"]) * ix / max(1, int(ax["n"]) - 1)
            lines.append(f"{x:.10g}")
    device_dir.mkdir(parents=True, exist_ok=True)
    target = device_dir / "pod_points.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(target)


# ---------------------------------------------------------------- 汇总入口


def onboard(
    model_path: str | Path,
    device_name: str,
    *,
    port: int = 2036,
    target_candidates: tuple[str, ...] = DEFAULT_TARGET_CANDIDATES,
    delta: float = 0.05,
    max_params: int = 12,
    do_solve: bool = True,
    grid: tuple[int, int, int] = (31, 23, 0),
    log=print,
) -> dict:
    """执行接入流程（第 1–5、8 步自动；第 6、7 步产出草稿）。"""
    import mph

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "device_name": device_name,
        "comsol_home": COMSOL_HOME,
        "steps": [],
        "errors": [],
    }

    def note(message: str) -> None:
        report["steps"].append(message)
        log(f"[onboard] {message}")

    client = mph.Client(port=port)
    # 先释放上一次接入遗留在 mphserver 里的模型：否则它会持有副本文件锁，导致本次复制失败
    _safe(lambda: client.clear())
    report["staging"] = stage = stage_model(Path(model_path), device_name)
    note(f"第1步 只读复制完成 → {stage['staged']}（第 {stage['copy_index']} 次接入，"
         f"原件哈希 {stage['source_sha256'][:12]}…）")
    if stage["source_lock_present"]:
        note("⚠️ 原文件旁存在 .lock（可能被 COMSOL GUI 打开）——本流程只操作副本，不受影响")

    model = client.load(stage["staged"])
    java = model.java
    note(f"已连接 mphserver:{port}（COMSOL {client.version}）并加载副本")

    device = inspect_device(model, java)
    report["device"] = device
    note(f"第2步 设备信息：组件={device['components']}，物理场={[p['type'] for p in device['physics']]}，"
         f"研究={device['studies']}")

    comp_tag = (device["components"] or [None])[0]
    geom_tag = (device.get("geometry", {}).get(comp_tag, {}).get("geom") or [None])[0]
    mesh_tag = (device.get("geometry", {}).get(comp_tag, {}).get("mesh") or [None])[0]
    if not (comp_tag and geom_tag and mesh_tag and device["studies"]):
        report["errors"].append("缺少组件/几何/网格/研究，无法继续接入流程")
        return report
    report["geometry_entity_counts"] = device["geometry"][comp_tag]["entity_counts"]
    report["space_dim"] = device["geometry"][comp_tag]["space_dim"]

    study = device["studies"][0]
    t0 = time.perf_counter()
    model.solve(study)
    report["baseline_solve_seconds"] = round(time.perf_counter() - t0, 2)
    note(f"第5步 基线求解完成：{report['baseline_solve_seconds']} s")

    targets, target_failures = probe_targets(model, target_candidates)
    report["targets"] = targets
    report["target_probe_failures"] = target_failures
    note(f"第5步 可用目标量：{list(targets.keys())}（失败候选 {len(target_failures)} 个）")

    report["parameter_audit"] = audit_parameters(
        model, java, study, comp_tag, geom_tag, mesh_tag, targets,
        delta=delta, max_params=max_params, do_solve=do_solve, log=log,
    )
    note(f"第3/4步 参数审计完成：白名单 {len(report['parameter_audit']['whitelist'])} 个，"
         f"跳过 {len(report['parameter_audit']['skipped'])} 个，"
         f"耗时 {report['parameter_audit']['audit_seconds']} s")

    report["public_point_set"] = define_public_point_set(
        report["parameter_audit"]["baseline"], nx=grid[0], ny=grid[1], nz=grid[2]
    )
    note(f"第8步 公共点集：{report['public_point_set']['grid_points']} 点")

    report["pending_human"] = [
        "第6步 目标口径确认：f_r / k_eff² / Q 的确切定义（口径差异常达几个百分点，必须人工确认）",
        "第7步 各参数的取值范围与类型（连续/离散档位）——本模块不猜范围",
        "结构变体清单（预先批准哪些结构改动）",
    ]
    report["device_spec_draft"] = build_device_spec_draft(report)
    note("接入流程自动部分完成；第 6、7 步需人工确认（见 pending_human）")
    return report


def build_device_spec_draft(report: dict) -> dict:
    """产出 `device_spec.yaml` 草稿：参数、目标、公共点集、研究、待填空。"""
    params = []
    for item in report.get("parameter_audit", {}).get("whitelist", []):
        params.append({
            "name": item["name"],
            "original": item["original"],
            "type": "continuous",           # 待人工确认是否为离散工艺档位
            "range": None,                  # ← 必须由用户给出；本模块不猜
            "auto_adjust_ok": True,
            "evidence": item["evidence"],
        })
    for item in report.get("parameter_audit", {}).get("skipped", []):
        params.append({
            "name": item["name"],
            "original": item.get("value"),
            "type": "derived_or_manual",
            "range": None,
            "auto_adjust_ok": False,
            "reason": item.get("reason"),
        })
    return {
        "device": report.get("device_name"),
        "source_sha256": report.get("staging", {}).get("source_sha256"),
        "space_dim": report.get("space_dim"),
        "studies": report.get("device", {}).get("studies"),
        "physics": report.get("device", {}).get("physics"),
        "parameters": params,
        "targets": {"caliber_id": "caliber-v1-draft", "expressions": list(report.get("targets", {}).keys())},
        "public_point_set": report.get("public_point_set"),
        "pending": report.get("pending_human", []),
    }


def save_report(report: dict, device_name: str) -> dict[str, str]:
    """把接入产物写入 `work/devices/<name>/`。"""
    import yaml

    device_dir = work_root() / "devices" / device_name
    device_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "device_report": device_dir / "device_report.json",
        "param_audit": device_dir / "param_audit.json",
        "device_spec": device_dir / "device_spec.yaml",
    }
    paths["device_report"].write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    paths["param_audit"].write_text(
        json.dumps(report.get("parameter_audit", {}), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    paths["device_spec"].write_text(
        yaml.safe_dump(report.get("device_spec_draft", {}), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    points_file = write_public_points(device_dir, report.get("public_point_set", {}))
    if points_file:
        paths["pod_points"] = Path(points_file)
    return {key: str(path) for key, path in paths.items()}
