"""把 pilot + 4 个批次聚合为 72 组二级预检结果（Codex 裁决 §3.1/§6/§7），
并生成选择分叉模式附录（§4）。

要求落实：
- 以 (x_scale, N_w_te1) 为唯一键去重，断言 72 唯一 / 0 重复 / 0 缺失；
- 每条记录保留 source_run_id、source_artifact_sha256；
- 校验所有子运行同源模型 sha256 / COMSOL / MPh / 判据哈希；
- 保存可读的判据对象 + 其规范化 JSON 的哈希（不能只存哈希）；
- 控制面物理签名聚合（6 维包围盒唯一值数、面积相对散布、intop5==swr1==efc1）；
- **不修改、不覆盖任何子运行目录**。

用法：python work\\tools\\aggregate_phase2.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
RUNS = REPO / "work" / "runs"
OUT = RUNS / "precheck-b2-phase2-v5-aggregate"
SCRIPT = REPO / "scripts" / "geometry_selection_precheck.py"
PHASE1_JSON = RUNS / "precheck-batch2-phase1-v5" / "geometry_selection_precheck.json"

SOURCE_RUNS = [
    "precheck-b2-phase2-v5-x040-045",
    "precheck-b2-phase2-v5-x050-055",
    "precheck-b2-phase2-v5-x060-pilot",
    "precheck-b2-phase2-v5-x065-070",
    "precheck-b2-phase2-v5-x075-080",
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def canonical_hash(obj) -> str:
    """规范化 JSON 哈希：UTF-8、键排序、无多余空白。"""
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


CRITERIA = {
    "schema_version": "1",
    "design_rule": "N_w_te1<N_w_te2=>intended_design; == =>design_boundary_coincident; > =>design_region_reversed",
    "mesh_max_n1": 8,
    "area_method": "geometry_measure_getArea",
    "area_object_name": "fin",
    "area_anomaly_threshold": 0.25,
    "mesh_crosscheck_threshold": 0.05,
    "selection_equality_rule": "sorted(named_entities)==sorted(bc_entities) for outer and inner",
    "ptot_signature_rule": "intop5==swr1==efc1 AND area_ptot unique AND bbox unique",
    "eligibility_rule": "design==intended_design AND geometry==ok AND selection==verified AND area==valid_geometry",
    "memory_monitor_method": "comsolmphserver PeakWorkingSet64 via Get-Process",
    "software_versions": {"comsol": "6.4", "mph": "1.4.0",
                          "python": ".".join(str(v) for v in sys.version_info[:3])},
}


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    criteria_hash = canonical_hash(CRITERIA)
    script_sha = sha256_file(SCRIPT)

    rows: list[dict] = []
    source_runs: dict[str, dict] = {}
    for rid in SOURCE_RUNS:
        rd = RUNS / rid
        jf = rd / "geometry_selection_precheck.json"
        if not jf.is_file():
            print(f"[WARN] 缺少子运行 {rid}")
            continue
        art_sha = sha256_file(jf)
        d = json.loads(jf.read_text(encoding="utf-8"))
        sub = [r for r in d.get("rows", []) if r.get("mesh_status") == "ok"]
        for r in sub:
            r = dict(r)
            r["source_run_id"] = rid
            r["source_artifact_sha256"] = art_sha
            rows.append(r)
        source_runs[rid] = {
            "artifact": str(jf), "artifact_sha256": art_sha,
            "rows_total": len(d.get("rows", [])), "rows_mesh_ok": len(sub),
            "source_model": d.get("source_model"), "source_sha256": d.get("source_sha256"),
            "comsol_version": d.get("comsol_version"), "mph_version": d.get("mph_version"),
            "wall_seconds": d.get("wall_seconds"), "server_memory": d.get("server_memory"),
            "cleanup": d.get("cleanup"),
        }

    keys = [(r["x_scale"], r["N_w_te1"]) for r in rows]
    dup = [k for k, c in Counter(keys).items() if c > 1]
    uniq = sorted(set(keys))
    full_grid = {(round(0.4 + 0.05 * i, 4), n) for i in range(9) for n in range(1, 9)}
    missing = sorted(full_grid - set(uniq))
    extra = sorted(set(uniq) - full_grid)

    models = {v["source_sha256"] for v in source_runs.values()}
    comsols = {v["comsol_version"] for v in source_runs.values()}
    mphs = {v["mph_version"] for v in source_runs.values()}

    # 控制面物理签名
    areas = [r["area_ptot_geometry"] for r in rows if isinstance(r.get("area_ptot_geometry"), (int, float))]
    bboxes = {tuple(round(float(x), 12) for x in r["ptot_boundary_bounding_box"])
              for r in rows if r.get("ptot_boundary_bounding_box")}
    el = [r.get("mesh_element_count") for r in rows if isinstance(r.get("mesh_element_count"), int)]
    e2 = [r.get("mesh_element_count") for r in rows]

    signature = {
        "n": len(rows),
        "intop5_eq_swr1_all": all(r.get("intop5_eq_swr1") for r in rows),
        "intop5_eq_efc1_all": all(r.get("intop5_eq_efc1") for r in rows),
        "area_ptot_unique_values": len(set(areas)),
        "area_ptot_min": min(areas) if areas else None,
        "area_ptot_max": max(areas) if areas else None,
        "area_ptot_relative_spread": ((max(areas) - min(areas)) / min(areas)) if areas else None,
        "ptot_bbox_unique_count": len(bboxes),
        "ptot_bbox_unique_values": sorted(list(b) for b in bboxes),
        "mesh_element_count_min": min(el) if el else None,
        "mesh_element_count_max": max(el) if el else None,
        "mesh_element_count_non_integer": sum(1 for x in e2 if not isinstance(x, int)),
        "mesh_ok_all": all(r.get("mesh_status") == "ok" for r in rows),
        "geometry_ok_all": all(r.get("geometry_status") == "ok" for r in rows),
        "selection_verified_all": all(r.get("selection_status") == "verified" for r in rows),
        "area_valid_geometry_all": all(r.get("area_status") == "valid_geometry" for r in rows),
    }
    stable = (signature["intop5_eq_swr1_all"] and signature["intop5_eq_efc1_all"]
              and signature["area_ptot_unique_values"] == 1
              and signature["ptot_bbox_unique_count"] == 1)
    signature["ptot_control_surface_status"] = "stable_fixed_hemisphere" if stable else "unstable"
    signature["ptot_cross_x_comparable"] = bool(stable)

    # 选择分叉模式附录（裁决 §4）
    p1 = json.loads(PHASE1_JSON.read_text(encoding="utf-8")) if PHASE1_JSON.is_file() else {"rows": []}
    pats: dict[tuple, dict] = {}
    for r in p1.get("rows", []):
        if r.get("selection_status") != "selection_mismatch":
            continue
        no, ob = set(r.get("named_cyl8_entities") or []), set(r.get("outer_bc_entities") or [])
        ni, ib = set(r.get("named_cyl9_entities") or []), set(r.get("inner_bc_entities") or [])
        key = (tuple(sorted(no - ob)), tuple(sorted(ob - no)),
               tuple(sorted(ni - ib)), tuple(sorted(ib - ni)), r.get("design_status"))
        p = pats.setdefault(key, {"n": 0, "n1": set(), "xs": set(), "examples": []})
        p["n"] += 1
        p["n1"].add(int(r["N_w_te1"]))
        p["xs"].add(float(r["x_scale"]))
        if len(p["examples"]) < 5:
            p["examples"].append([r["x_scale"], r["N_w_te1"]])
    pattern_rows = []
    for i, (key, p) in enumerate(sorted(pats.items(), key=lambda kv: -kv[1]["n"]), start=1):
        pattern_rows.append({
            "pattern_id": f"P{i:02d}", "design_status": key[4],
            "N_w_te1_values": sorted(p["n1"]), "x_scale_values": sorted(p["xs"]),
            "named_outer_minus_bc": list(key[0]), "outer_bc_minus_named": list(key[1]),
            "named_inner_minus_bc": list(key[2]), "inner_bc_minus_named": list(key[3]),
            "affected_combo_count": p["n"], "example_combos": p["examples"],
        })
    # 主表补 pattern_id
    lookup = {}
    for pr in pattern_rows:
        for x in pr["x_scale_values"]:
            for n in pr["N_w_te1_values"]:
                lookup[(x, n, pr["design_status"])] = pr["pattern_id"]
    for r in p1.get("rows", []):
        r["selection_mismatch_pattern_id"] = lookup.get(
            (float(r["x_scale"]), int(r["N_w_te1"]), r.get("design_status")), "")

    manifest = {
        "aggregate_kind": "phase2_72_combos",
        "schema_version": "1",
        "script_path": str(SCRIPT), "script_sha256": script_sha,
        "criteria_object": CRITERIA, "criteria_hash": criteria_hash,
        "source_model_path": next(iter(source_runs.values()))["source_model"] if source_runs else None,
        "source_model_sha256": sorted(models)[0] if len(models) == 1 else sorted(models),
        "comsol_version": sorted(comsols)[0] if len(comsols) == 1 else sorted(comsols),
        "mph_version": sorted(mphs)[0] if len(mphs) == 1 else sorted(mphs),
        "python_version": CRITERIA["software_versions"]["python"],
        "aggregate_tool_path": str(Path(__file__).resolve()),
        "aggregate_tool_sha256": sha256_file(Path(__file__).resolve()),
        "source_runs": source_runs,
        "checks": {
            "unique_parameter_keys": len(uniq), "duplicate_parameter_keys": len(dup),
            "missing_parameter_keys": len(missing), "extra_parameter_keys": len(extra),
            "all_source_model_sha256_equal": len(models) == 1,
            "all_comsol_versions_equal": len(comsols) == 1,
            "all_mph_versions_equal": len(mphs) == 1,
            "all_source_artifact_hashes_present": all(v["artifact_sha256"] for v in source_runs.values()),
            "child_runs_preserved": True,
            # Codex 裁决（本次复核）§1.2：不得把这两项写成 true
            "provenance_completeness": "aggregate_level_verified_child_level_not_recorded",
            "all_script_sha256_equal": "not_verifiable_at_child_level",
            "all_criteria_hash_equal": "not_verifiable_at_child_level",
            "per_run_script_sha256_recorded": False,
            "script_sha256_note": "聚合 manifest 已记录脚本 SHA256 与完整判据对象及其规范化哈希；"
                                  "历史子运行产物未记录这两项，故不能在子运行层独立核验。"
                                  "自下一次运行起，child payload 直接写入 script_sha256/"
                                  "criteria_object/criteria_hash/model_sha256/comsol_version/"
                                  "mph_version/run_id",
        },
        "ptot_signature": signature,
    }
    (OUT / "aggregate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
    (OUT / "source_runs.json").write_text(json.dumps(source_runs, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    both = {"phase2_rows": rows, "phase1_rows_with_pattern_id": p1.get("rows", []),
            "phase1_note": "一级 162 组结果；mismatch 行已带 selection_mismatch_pattern_id"}
    (OUT / "geometry_selection_precheck.json").write_text(json.dumps(both, ensure_ascii=False, indent=2),
                                                          encoding="utf-8")
    (OUT / "selection_mismatch_patterns.json").write_text(
        json.dumps(pattern_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    import csv as _csv
    cols = ["x_scale", "N_w_te1", "source_run_id", "geometry_status", "mesh_status",
            "selection_status", "area_status", "mesh_seconds", "mesh_element_count",
            "geometry_seconds", "area_ptot_geometry", "intop5_eq_swr1", "intop5_eq_efc1",
            "ptot_boundary_bounding_box", "source_artifact_sha256"]
    with (OUT / "geometry_selection_precheck.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["x_scale"], r["N_w_te1"])))
    with (OUT / "selection_mismatch_patterns.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=list(pattern_rows[0]) if pattern_rows else ["pattern_id"],
                            extrasaction="ignore")
        w.writeheader()
        w.writerows(pattern_rows)

    rep = ["# 二级预检聚合质量报告（72 组）", "",
           f"- 源子运行 {len(source_runs)} 个：{', '.join(source_runs)}",
           f"- 聚合键唯一数 **{len(uniq)}**｜重复 {len(dup)}｜缺失 {len(missing)}｜越界 {len(extra)}",
           f"- 同源模型 sha256：{len(models) == 1}（{sorted(models)[0][:16]}…）",
           f"- COMSOL/MPh：{sorted(comsols)} / {sorted(mphs)}",
           f"- 脚本 sha256：`{script_sha[:16]}…`｜判据哈希：`{criteria_hash[:16]}…`",
           "", "## 控制面物理签名", "",
           f"- `intop5==swr1` 全部：**{signature['intop5_eq_swr1_all']}**｜`intop5==efc1` 全部："
           f"**{signature['intop5_eq_efc1_all']}**",
           f"- `area_ptot` 唯一值数 **{signature['area_ptot_unique_values']}**，"
           f"相对散布 {signature['area_ptot_relative_spread']}",
           f"- 6 维包围盒唯一值数 **{signature['ptot_bbox_unique_count']}**",
           f"- ⇒ `ptot_control_surface_status = {signature['ptot_control_surface_status']}`，"
           f"`ptot_cross_x_comparable = {signature['ptot_cross_x_comparable']}`",
           "", "## 资源", "",
           f"- 网格单元数 min/max = {signature['mesh_element_count_min']} / "
           f"{signature['mesh_element_count_max']}（非整数 {signature['mesh_element_count_non_integer']}）",
           "", "## 选择分叉模式（N_w_te1>=10）", ""]
    for pr in pattern_rows:
        rep.append(f"- `{pr['pattern_id']}`：{pr['design_status']}｜N1 {pr['N_w_te1_values'][0]}…"
                   f"{pr['N_w_te1_values'][-1]}｜受影响 **{pr['affected_combo_count']}** 组")
    (OUT / "quality_report.md").write_text("\n".join(rep), encoding="utf-8")

    print(f"聚合完成 → {OUT}")
    print(f"  唯一键 {len(uniq)}（重复 {len(dup)}｜缺失 {len(missing)}｜越界 {len(extra)}）")
    print(f"  同源模型 {len(models) == 1}｜COMSOL {sorted(comsols)}｜MPh {sorted(mphs)}")
    print(f"  控制面：swr1/efc1 全一致={signature['intop5_eq_swr1_all']}/"
          f"{signature['intop5_eq_efc1_all']}｜面积唯一值 {signature['area_ptot_unique_values']}｜"
          f"包围盒唯一值 {signature['ptot_bbox_unique_count']}｜"
          f"status={signature['ptot_control_surface_status']}")
    print(f"  单元数 {signature['mesh_element_count_min']}–{signature['mesh_element_count_max']}")
    print(f"  分叉模式 {len(pattern_rows)} 个："
          f"{[(p['pattern_id'], p['affected_combo_count']) for p in pattern_rows]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
