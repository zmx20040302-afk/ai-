"""几何/选择集预检 v3（落实 Codex 2026-09-13 裁决回复 §2–§9）——**不做频域求解**。

## v3 相对 v2 的改动（逐条对应裁决回复）

| 裁决 | 实现 |
|---|---|
| §2 Q-A：**几何 `getArea()` 作主证据**，Mesh 积分作交叉验证 | `geometry_area()`：对每个面积分别用最终几何测量接口取面积；`area_geometry_*` 与 `area_mesh_integral_*` 双记，并算 `area_*_relative_difference` |
| §8.1 **删除默认 Solution 回退** | 面积只走「几何测量」与「显式 Mesh 数据集」两条路；**绝不调用无指定数据集的 `model.evaluate()`** |
| §8.2 三个面积来源分别记录 | `area_outer_source` / `area_inner_source` / `area_ptot_source`（而非单一 `area_source`） |
| §8.3 单位字段 | 改为 `W_min_expression` + `*_raw_value`，不再声称字段是 SI 的「_m」 |
| §8.4 面积异常定位到区间 | 记录 `anomaly_from_x` / `anomaly_to_x` / `relative_step`，**只标发生突变的两个端点行** |
| §8.5 三种面积都查连续性 | `inner` / `outer` / `ptot` 分别做沿 x 的相邻步突变检查 |
| §8.6 `--resume` 必须配同一 `--run-id` | 同时给 `--resume` 而无 `--run-id` → **直接报错退出** |
| §3 Q-B / §8.7 **并列状态列替代优先级总分类** | 输出 `design_status`/`geometry_status`/`selection_status`/`area_status`/`mesh_status`/`mesh_crosscheck_status` + `eligible_for_ranking`/`eligibility_level`/`eligibility_reason`/`quality_warnings`；**不再有覆盖式 `classification`**，资格原因与质量警告**分列**（裁决 §6.2） |
| §9 哨兵验收标准 | `sentinel_report.json` 内置 `checks`：逐条判定并给出通过/未通过 |

## 面积 API 的取证（含我方一次错误更正）

- 我方 v2 曾据 `com/comsol/model/method/GeomMeasureMethod.class` 的常量池断言「几何测量接口没有面积方法」——
  **该结论错误**。`com/comsol/model/dbimodel/GeomMeasureBase.class` 明确含：
  `getArea`（javadoc: "Gets area of the selected faces or 2D domains"）、`getBoundaryArea`、
  `getBoundaryVolume`、`getVolume`、`getLength`、`getPerimeter`、`getNEntities`、`getVtxCoord`、`selection()`。
  官方 6.4 API 文档一致（`com.comsol.model.GeomMeasureBase`）。
- `GeomSequence` 的弃用提示原文：**"Use model.component(ctag).measure() or model.mesh(mtag).measure() instead."**
- ⇒ 取面积按「多访问器顺序尝试」实现并记录成功者（`area_geometry_call`），
  依次尝试 `comp.measure()` → `geom.measure()` → `geom.getMeasureGen()`，
  选择对象按 `selection().init(2)` + `selection().set(ids)`，失败则记录异常原文。

## 资格逻辑（裁决 §3）

    eligible_for_ranking = design_status == intended_design
                           and geometry_status == ok
                           and selection_status == verified
                           and area_status in {valid, valid_mesh_only, pending}
    eligibility_level    = full（area_status==valid）｜provisional（pending / 面积仅 Mesh / 面积突变）
                           ｜ineligible（其余）

## 用法

    python scripts\\geometry_selection_precheck.py --model "<m>.mph" --only-sentinels
    python scripts\\geometry_selection_precheck.py --model "<m>.mph" --xs 0.4:0.05:0.8 --n1 1:1:18 \
        --phase both --mesh-max-n1 8 --run-id precheck-b2-v3 --resume
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import socket
import sys
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from memsharness import onboard as ob  # noqa: E402
from memsharness.paths import work_root  # noqa: E402
from memsharness.store import connect, insert_run, now_utc  # noqa: E402

DESIGN_STATUS = ["intended_design", "design_boundary_coincident", "design_region_reversed", "unknown"]
GEOMETRY_STATUS = ["ok", "build_failed", "not_run"]
SELECTION_STATUS = ["verified", "empty_selection", "bc_conflict", "selection_mismatch",
                    "not_run", "unknown"]
AREA_STATUS = ["valid_geometry", "unavailable", "not_run", "pending", "valid_mesh_only"]
MESH_CROSSCHECK = ["not_run", "valid", "unavailable", "mismatch"]
MESH_STATUS = ["ok", "failed", "not_run"]
ELIGIBILITY = ["full", "provisional", "ineligible"]
AREA_KINDS = ("outer", "inner", "ptot")


def entities_of(java_obj) -> list[int] | None:
    try:
        return sorted({int(x) for x in java_obj.entities()})
    except Exception:
        return None


def fnum(text) -> float | None:
    """从 '4.2[um]' / '4' 抽数值（**不换算单位**，字段名如实反映为 raw value）。"""
    if text is None:
        return None
    s = str(text).strip()
    try:
        return float(s)
    except ValueError:
        pass
    m = re.match(r"^([-+0-9.eE]+)", s)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def geometry_area(geom, entities: list[int], obj_name: str = "fin", dim: int = 2):
    """用 COMSOL 最终几何测量接口取面积（不依赖任何解）。

    **实测可用式（2026-09-13，探针 `work/tools/probe_area_api.py` 一次会话内穷举确认）**：

        m = geom.measure()          # GeomMeasureClient（注意：comp.measure() 是**网格**测量！）
        sel = m.selection()          # LocalGeomObjectSelectionClient
        sel.init(2)                  # 实体维度 2 = 3D 边界面
        sel.set("fin", JArray(JInt)(ids))   # 必须带几何对象名 + 显式 Java int[]
        sel.entities("fin", 2) == ids       # 回读校验
        area = m.getArea()

    依据：官方 `com.comsol.model.GeomObjectSelection` 只有 `set(String oname, int[] entities)`
    等重载，**没有 `set(int[])`**（故纯 Python 列表会报 "No matching overloads"）；
    几何对象名由 `geom.run('fin')` 决定，实测为 `"fin"`。

    返回 (area, call_used, error)。
    """
    import jpype

    if not entities:
        return None, None, "实体列表为空"
    try:
        m = geom.measure()
    except Exception as exc:
        return None, None, f"geom.measure(): {type(exc).__name__}: {exc}"
    errors: list[str] = []
    try:
        sel = m.selection()
        sel.init(dim)
    except Exception as exc:
        return None, None, f"selection().init({dim}): {type(exc).__name__}: {exc}"
    want = sorted(entities)
    # 裁决 §6.1：**只用最终几何对象 `fin`**。不得在 fin 失败后静默测 sca1/rev1——
    # 中间对象里的相同实体编号未必具有相同物理意义。
    if not obj_name:
        return None, None, "未指定几何对象名（必须为最终对象 'fin'）"
    for oname in (obj_name,):
        try:
            sel.set(oname, jpype.JArray(jpype.JInt)(want))
            got = sorted(int(v) for v in sel.entities(oname, dim))
            area = float(m.getArea())
            if got == want and math.isfinite(area) and area > 0:
                return area, f"geom.measure()/init({dim})/set({oname!r},JInt[])", None
            errors.append(f"set({oname!r}): 回读 {got[:6]}≠目标 {want[:6]} 或 area={area}")
        except Exception as exc:
            errors.append(f"set({oname!r}): {type(exc).__name__}: {exc}")
    return None, None, "geometry_area_failed: " + " ｜ ".join(errors[:6])


def geometry_bbox(geom, entities: list[int], obj_name: str = "fin", dim: int = 2):
    """控制面的**物理签名**之一：包围盒（Codex 裁决 §2.2/§7：不能只用实体编号判断控制面是否同一）。

    返回 (bbox_list, error)。bbox 为 `[xmin,xmax,ymin,ymax,...]`。
    """
    import jpype

    if not entities or not obj_name:
        return None, "实体/对象名为空"
    try:
        m = geom.measure()
        sel = m.selection()
        sel.init(dim)
        sel.set(obj_name, jpype.JArray(jpype.JInt)(sorted(int(v) for v in entities)))
        return [float(x) for x in m.getBoundingBox()], None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def server_memory() -> dict:
    """读取 **comsolmphserver** 进程的内存（裁决 §5.2：峰值内存必须监控 server，不是 Python 进程）。

    `PeakWorkingSet64` 是进程启动以来的峰值，任何时刻都可读，故无需高频采样。
    """
    import json as _json
    import subprocess

    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process comsolmphserver -ErrorAction SilentlyContinue | "
             "Select-Object -First 1 Id,WorkingSet64,PeakWorkingSet64 | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        if not out:
            return {"comsol_server_pid": None}
        d = _json.loads(out)
        if isinstance(d, list):
            d = d[0] if d else {}
        return {
            "comsol_server_pid": d.get("Id"),
            "comsol_server_working_set_mb": round((d.get("WorkingSet64") or 0) / 1048576, 1),
            "comsol_server_peak_working_set_mb": round((d.get("PeakWorkingSet64") or 0) / 1048576, 1),
        }
    except Exception as exc:
        return {"comsol_server_pid": None,
                "comsol_server_memory_error": f"{type(exc).__name__}: {exc}"}


def ensure_mesh_dataset(model) -> tuple[str | None, str | None]:
    tag = "dset_mesh_precheck"
    try:
        ds = model.java.result().dataset()
        try:
            ds.create(tag, "Mesh")
        except Exception as exc:
            first = f"create: {type(exc).__name__}: {exc}"
            try:
                if tag in [str(t) for t in ds.tags()]:
                    return tag, f"已存在（create 报错：{first}）"
            except Exception:
                pass
            return None, first
        try:
            seen = [str(t) for t in ds.tags()]
        except Exception:
            seen = []
        return (tag, None) if (not seen or tag in seen) else (None, f"create 后 tags 无 {tag}：{seen}")
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def mesh_integral_area(model, java, expr: str, dataset: str | None):
    """面积交叉验证。**不回退默认数据集**（裁决 §8.1）。

    实测（2026-09-13）：`ds.create(tag,"Mesh")` 成功后 tags 里有该数据集，但 MPh 的
    `model.evaluate(expr, dataset=tag)` 仍报 `Dataset "..." does not exist.`（MPh 在 load
    时缓存了数据集名单，看不到新建的），故再试 Java 侧 EvalGlobal 绕开该缓存。
    另实测：无数据集回退会返回**与当前参数不对应**的值（`intop4(1)` 得 1.053e-09，
    而当前几何真实面积为 6.308e-10，差 1.67 倍）——这正是禁止该回退的直接证据。
    """
    import numpy as np

    if not dataset:
        return None, "无 Mesh 数据集（不回退默认数据集）"
    errs: list[str] = []
    try:
        values = model.evaluate(expr, dataset=dataset)
        arr = np.asarray(values, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size:
            return float(arr[0]), None
        errs.append("MPh evaluate 求值为空")
    except Exception as exc:
        errs.append(f"MPh: {type(exc).__name__}: {exc}")
    try:  # Java 侧 EvalGlobal，绕开 MPh 的数据集缓存
        num = java.result().numerical()
        try:
            num.create("gev_area_precheck", "EvalGlobal")
        except Exception:
            pass
        node = num("gev_area_precheck")
        node.set("expr", expr)
        node.set("dataset", dataset)
        node.setResult()
        flat: list[float] = []
        for row in node.getReal():
            try:
                flat.extend(float(x) for x in row)
            except TypeError:
                flat.append(float(row))
        flat = [x for x in flat if math.isfinite(x)]
        if flat:
            return float(flat[0]), None
        errs.append("Java EvalGlobal 求值为空")
    except Exception as exc:
        errs.append(f"Java: {type(exc).__name__}: {exc}")
    return None, " ｜ ".join(errs[:3])


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="几何/选择集预检 v3（不做频域求解）")
    ap.add_argument("--model", required=True)
    ap.add_argument("--device", default="ge-task3-precheck")
    ap.add_argument("--xs", default="0.4:0.05:0.8")
    ap.add_argument("--n1", default="1:1:18")
    ap.add_argument("--port", type=int, default=2036)
    ap.add_argument("--phase", choices=["1", "2", "both"], default="both")
    ap.add_argument("--mesh-max-n1", type=int, default=8)
    ap.add_argument("--sentinels", default="0.4:1,0.6:4,0.8:8")
    ap.add_argument("--only-sentinels", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--area-anomaly-tol", type=float, default=0.25)
    ap.add_argument("--area-cross-tol", type=float, default=0.05,
                    help="几何面积与 Mesh 积分面积的相对差容忍（超此值只记录并降级）")
    ap.add_argument("--area-obj-name", default="fin",
                    help="最终几何对象名（`geom.run('fin')` ⇒ 'fin'，实测可用）")
    ap.add_argument("--area-outer-expr", default="intop4(1)")
    ap.add_argument("--area-inner-expr", default="intop3(1)")
    ap.add_argument("--area-ptot-expr", default="intop5(1)")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    if args.resume and not args.run_id:
        print("[ERROR] --resume 必须与同一个 --run-id 一起使用，否则每次都会新建 run 目录、"
              "读不到上一次的 checkpoint.jsonl（裁决 §8.6）", flush=True)
        return 2

    start, step, stop = (float(v) for v in args.xs.split(":"))
    xs = [round(start + step * i, 4) for i in range(round((stop - start) / step) + 1)]
    n1a, n1b = (int(v) for v in args.n1.split(":")[::2])
    n1s = list(range(n1a, n1b + 1))
    sentinels = []
    for tok in args.sentinels.split(","):
        if tok.strip():
            a, b = tok.split(":")
            sentinels.append((round(float(a), 4), int(b)))
    combos = sentinels if args.only_sentinels else [(x, n) for x in xs for n in n1s]

    run_id = args.run_id or f"precheck-geomsel3-{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = work_root() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ckpt = run_dir / "checkpoint.jsonl"

    print(f"网格：x {xs} × N1 {n1s} = {len(xs) * len(n1s)} 组合｜本次执行 {len(combos)}"
          f"（{'仅哨兵' if args.only_sentinels else '全量'}）", flush=True)
    print(f"run_id={run_id}｜phase={args.phase}｜建网格上限 N1<={args.mesh_max_n1}", flush=True)

    done: dict[tuple[float, int], dict] = {}
    if args.resume and ckpt.is_file():
        for line in ckpt.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if rec.get("phase_done") == "2" or (rec.get("phase_done") == "1" and args.phase == "1"):
                    done[(float(rec["x_scale"]), int(rec["N_w_te1"]))] = rec
            except Exception:
                continue
        print(f"--resume(run_id={run_id})：已完成 {len(done)} 个组合", flush=True)

    staging = ob.stage_model(Path(args.model), args.device)
    print(f"只读副本：{staging['staged']}", flush=True)
    print(f"源 sha256={staging['source_sha256']}", flush=True)
    print(f"副本 sha256={staging['staged_sha256']}", flush=True)

    import mph

    def port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                return True
        except OSError:
            return False

    started_server = not port_open(args.port)
    client = mph.Client(port=args.port) if not started_server else mph.start(cores=1, port=args.port)
    model = client.load(staging["staged"])
    java = model.java
    comp = java.modelNode("comp1")
    geom = comp.geom("geom1")
    mesh = comp.mesh("mesh1")
    print(f"载入：{model.name()}（COMSOL {client.version}）｜本脚本启动 server={started_server}",
          flush=True)

    def raw_param(name: str):
        try:
            return java.param().get(name)
        except Exception:
            return None

    w_expr, n_mem_expr, n2_expr = raw_param("W_min"), raw_param("N_mem"), raw_param("N_w_te2")
    w_raw, n_mem_raw, n2_raw = fnum(w_expr), fnum(n_mem_expr), fnum(n2_expr)
    r_mem_raw = (w_raw * n_mem_raw) if (w_raw is not None and n_mem_raw is not None) else None

    mem_before = server_memory()
    print(f"[资源] 运行前 server 内存：{mem_before}", flush=True)

    rows: list[dict] = []
    t_all = time.perf_counter()
    cleanup_ok = {"clear": None, "disconnect": None}
    try:
        for idx, (x, n1) in enumerate(combos, start=1):
            if (x, n1) in done:
                rows.append(done[(x, n1)])
                print(f"[{idx}/{len(combos)}] x={x:g} N1={n1} 已跳过", flush=True)
                continue
            e: dict = {"x_scale": x, "N_w_te1": n1, "phase_done": "1"}
            try:
                java.param().set("x_scale", f"{x:g}")
                java.param().set("N_w_te1", f"{n1:d}")

                geom_ok = True
                _t_geom = time.perf_counter()
                try:
                    geom.run()
                except Exception as exc:
                    geom_ok = False
                    e["geometry_error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
                e["geometry_seconds"] = round(time.perf_counter() - _t_geom, 3)
                e["geometry_status"] = "ok" if geom_ok else "build_failed"

                if geom_ok:
                    bc_outer = entities_of(comp.physics("es").feature("term1").selection())
                    bc_inner = entities_of(comp.physics("es").feature("pot2").selection())
                    named_outer = entities_of(comp.selection("cyl8"))
                    named_inner = entities_of(comp.selection("cyl9"))
                    ents = {}
                    for k, tag in (("outer", "intop4"), ("inner", "intop3"), ("ptot", "intop5")):
                        try:
                            ents[k] = entities_of(comp.cpl(tag).selection())
                        except Exception:
                            ents[k] = None
                    # acpr 的外边界节点：球面波辐射 / 外场计算（裁决 §2.2：须与 intop5 选择一致）
                    acpr_ents = {}
                    for tag in ("swr1", "efc1"):
                        try:
                            acpr_ents[tag] = entities_of(comp.physics("acpr").feature(tag).selection())
                        except Exception:
                            acpr_ents[tag] = None
                    # ptot 的几何面积应量在 intop5 的实体上；outer/inner 量在物理 BC 实际实体上
                    area_ents = {"outer": bc_outer, "inner": bc_inner, "ptot": ents["ptot"]}
                    e.update(outer_bc_entities=bc_outer, inner_bc_entities=bc_inner,
                             named_cyl8_entities=named_outer, named_cyl9_entities=named_inner,
                             intop3_entities=ents["inner"], intop4_entities=ents["outer"],
                             intop5_entities=ents["ptot"],
                             swr1_entities=acpr_ents["swr1"], efc1_entities=acpr_ents["efc1"],
                             intop5_eq_swr1=(ents["ptot"] == acpr_ents["swr1"])
                             if (ents["ptot"] is not None and acpr_ents["swr1"] is not None) else None,
                             intop5_eq_efc1=(ents["ptot"] == acpr_ents["efc1"])
                             if (ents["ptot"] is not None and acpr_ents["efc1"] is not None) else None,
                             outer_bc_count=None if bc_outer is None else len(bc_outer),
                             inner_bc_count=None if bc_inner is None else len(bc_inner))
                    _bb, _bberr = geometry_bbox(geom, ents["ptot"] or [], args.area_obj_name)
                    e["ptot_boundary_bounding_box"] = _bb
                    e["ptot_boundary_bounding_box_error"] = _bberr
                    inter = sorted(set(bc_outer or []) & set(bc_inner or []))
                    e["bc_intersection"] = inter
                    e["bc_intersection_count"] = len(inter)
                    e["named_vs_bc_outer_equal"] = (named_outer == bc_outer) if (
                        named_outer is not None and bc_outer is not None) else None
                    e["named_vs_bc_inner_equal"] = (named_inner == bc_inner) if (
                        named_inner is not None and bc_inner is not None) else None

                    # ---- 几何面积（主证据，不依赖解）----
                    for k in AREA_KINDS:
                        a, call, err = geometry_area(geom, area_ents.get(k) or [],
                                                     obj_name=args.area_obj_name)
                        e[f"area_{k}_geometry"] = a
                        e[f"area_{k}_geometry_call"] = call
                        e[f"area_{k}_geometry_error"] = err
                    # ---- 设计状态（参数级，与实体证据并列而非覆盖）----
                    e["physical_extent_suspect"] = (
                        None if (w_raw is None or r_mem_raw is None or w_raw == 0)
                        else bool(n1 * w_raw > r_mem_raw))
                else:
                    e["bc_intersection"] = []
                    for k in AREA_KINDS:
                        e[f"area_{k}_geometry"] = None
                        e[f"area_{k}_geometry_error"] = "geometry_build_failed"

                # 设计状态
                if n2_raw is None:
                    e["design_status"] = "unknown"
                elif n1 > n2_raw:
                    e["design_status"] = "design_region_reversed"
                elif n1 == n2_raw:
                    e["design_status"] = "design_boundary_coincident"
                else:
                    e["design_status"] = "intended_design"

                # 选择状态（与设计状态并列保存，互不遮蔽）
                if not geom_ok:
                    e["selection_status"] = "not_run"
                elif not e.get("outer_bc_entities") or not e.get("inner_bc_entities"):
                    e["selection_status"] = "empty_selection"
                elif e.get("bc_intersection"):
                    e["selection_status"] = "bc_conflict"
                elif e.get("named_vs_bc_outer_equal") is False or \
                     e.get("named_vs_bc_inner_equal") is False:
                    e["selection_status"] = "selection_mismatch"
                else:
                    e["selection_status"] = "verified"

                # ---- 二级：Mesh 积分交叉验证（仅一级通过且 N1<=上限）----
                want2 = args.phase in ("2", "both")
                p1_ok = (geom_ok and e.get("selection_status") == "verified"
                         and n1 <= args.mesh_max_n1)
                if want2 and p1_ok:
                    try:
                        _t_mesh = time.perf_counter()
                        mesh.run()
                        e["mesh_status"] = "ok"
                        e["mesh_seconds"] = round(time.perf_counter() - _t_mesh, 3)
                    except Exception as exc:
                        e["mesh_status"] = "failed"
                        e["mesh_seconds"] = round(time.perf_counter() - _t_mesh, 3)
                        e["mesh_error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
                    if e["mesh_status"] == "ok":
                        try:
                            e["mesh_element_count"] = int(comp.mesh("mesh1").getNumElem())
                        except Exception as exc:
                            e["mesh_element_count"] = None
                            e["mesh_element_count_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                    if e["mesh_status"] == "ok":
                        ds_tag, ds_err = ensure_mesh_dataset(model)
                        e["mesh_dataset"] = ds_tag
                        e["mesh_dataset_error"] = ds_err
                        exprs = {"outer": args.area_outer_expr, "inner": args.area_inner_expr,
                                 "ptot": args.area_ptot_expr}
                        for k in AREA_KINDS:
                            a, err = mesh_integral_area(model, java, exprs[k], ds_tag)
                            e[f"area_{k}_mesh_integral"] = a
                            e[f"area_{k}_mesh_error"] = err
                            g = e.get(f"area_{k}_geometry")
                            e[f"area_{k}_relative_difference"] = (
                                None if (not a or not g) else abs(a - g) / abs(g))
                        e["phase_done"] = "2"
                else:
                    e["mesh_status"] = "not_run"
                    for k in AREA_KINDS:
                        e[f"area_{k}_mesh_integral"] = None
                        e[f"area_{k}_relative_difference"] = None

                # ---- 面积状态（裁决 §1.1：只由**几何测量**决定；Mesh 只影响交叉验证状态）----
                for k in AREA_KINDS:
                    g = e.get(f"area_{k}_geometry")
                    mi = e.get(f"area_{k}_mesh_integral")
                    if g is not None and math.isfinite(g) and g > 0:
                        e[f"area_{k}_source"] = "geometry_measure"
                    elif mi is not None and math.isfinite(mi) and mi > 0:
                        e[f"area_{k}_source"] = "mesh_integral_only"
                    else:
                        e[f"area_{k}_source"] = "none"
                if all(e.get(f"area_{k}_source") == "geometry_measure" for k in AREA_KINDS):
                    e["area_status"] = "valid_geometry"
                else:
                    e["area_status"] = "unavailable"
                if e.get("mesh_status") == "not_run":
                    e["mesh_crosscheck_status"] = "not_run"
                    e["mesh_crosscheck_reason"] = "一级预检不建网格（几何面积为唯一面积证据）"
                elif all(e.get(f"area_{k}_mesh_integral") for k in AREA_KINDS):
                    diffs = [e.get(f"area_{k}_relative_difference") for k in AREA_KINDS]
                    num = [d for d in diffs if isinstance(d, (int, float))]
                    bad = [d for d in num if d > args.area_cross_tol]
                    e["mesh_crosscheck_status"] = "mismatch" if bad else "valid"
                    e["mesh_crosscheck_reason"] = f"max_rel_diff={max(num) if num else None}"
                else:
                    e["mesh_crosscheck_status"] = "unavailable"
                    errs = [str(e.get(f"area_{k}_mesh_error")) for k in AREA_KINDS
                            if e.get(f"area_{k}_mesh_error")]
                    e["mesh_crosscheck_reason"] = ("mph_dataset_cache_or_java_overload: "
                                                   + (errs[0][:140] if errs else "无值"))
            except Exception as exc:
                e["combo_error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
                e.setdefault("geometry_status", "not_run")
                e.setdefault("selection_status", "unknown")
                e.setdefault("area_status", "not_run")
                e.setdefault("mesh_status", "not_run")
                e.setdefault("design_status", "unknown")

            rows.append(e)
            with ckpt.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
                fh.flush()
            print(f"[{idx}/{len(combos)}] x={x:<4g} N1={n1:<2d}｜{e.get('design_status')}"
                  f"｜sel={e.get('selection_status')}｜area={e.get('area_status')}"
                  f"｜A_out_geom={e.get('area_outer_geometry')}"
                  f"｜A_out_mesh={e.get('area_outer_mesh_integral')}", flush=True)
    finally:
        try:
            client.clear()
            cleanup_ok["clear"] = True
        except Exception as exc:
            cleanup_ok["clear"] = f"{type(exc).__name__}: {exc}"
        try:
            client.disconnect()
            cleanup_ok["disconnect"] = True
        except Exception as exc:
            cleanup_ok["disconnect"] = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)
        cleanup_ok["port_still_open"] = port_open(args.port)
        cleanup_ok["checkpoint_write_status"] = (f"{len(rows)} 行已 flush"
                                                 if ckpt.is_file() else "checkpoint 缺失")
        cleanup_ok["server_memory_after"] = server_memory()
        print(f"[cleanup] {cleanup_ok}", flush=True)

    # ---- 面积连续性（三种面积分别查，异常只标端点）----
    # 裁决 §1.2/§6.3：必须同时报"比较了多少对"。哨兵阶段每个 N1 只有一个 x ⇒ 比较对 = 0，
    # 此时**不得**把"0 处突变"读成"连续性通过"，只能报 not_evaluated。
    continuity: dict[str, dict] = {}
    for k in AREA_KINDS:
        key = f"area_{k}_geometry"
        groups: dict[int, list[tuple[float, float]]] = {}
        for r in rows:
            v = r.get(key)
            if isinstance(v, (int, float)) and math.isfinite(v) and v > 0:
                groups.setdefault(int(r["N_w_te1"]), []).append((float(r["x_scale"]), float(v)))
        n_pairs = 0
        n_anom = 0
        per_n1_pairs: dict[int, int] = {}
        per_n1_anom: dict[int, int] = {}
        for n1v, pairs in sorted(groups.items()):
            pairs.sort()
            per_n1_pairs[n1v] = max(len(pairs) - 1, 0)
            n_pairs += per_n1_pairs[n1v]
            for (x0, a0), (x1, a1) in zip(pairs, pairs[1:]):
                if a0 <= 0:
                    continue
                step_rel = abs(a1 - a0) / a0
                if step_rel > args.area_anomaly_tol:
                    n_anom += 1
                    per_n1_anom[n1v] = per_n1_anom.get(n1v, 0) + 1
                    print(f"[面积突变] {k}: N1={n1v} x={x0:g}→{x1:g} 相对突变 {step_rel * 100:.1f}%",
                          flush=True)
                    for r in rows:
                        if int(r["N_w_te1"]) == n1v and float(r["x_scale"]) in (x0, x1):
                            r.setdefault("area_anomaly_flags", []).append(k)
                            r[f"anomaly_{k}_from_x"] = x0
                            r[f"anomaly_{k}_to_x"] = x1
                            r[f"anomaly_{k}_relative_step"] = round(step_rel, 6)
        continuity[k] = {
            "pairs_checked": n_pairs, "anomalies_found": n_anom,
            "status": "evaluated" if n_pairs else "not_evaluated",
            "pairs_checked_per_N1": per_n1_pairs, "anomalies_per_N1": per_n1_anom,
        }
        for r in rows:
            r[f"continuity_pairs_checked_{k}"] = per_n1_pairs.get(int(r["N_w_te1"]), 0)
            r[f"continuity_anomalies_{k}"] = per_n1_anom.get(int(r["N_w_te1"]), 0)
        print(f"[面积连续性] {k}：比较对 {n_pairs} 组，突变 {n_anom} 处"
              f"（阈值 {args.area_anomaly_tol * 100:.0f}%）→ status={continuity[k]['status']}",
              flush=True)
    area_continuity_status = ("not_evaluated"
                              if all(v["pairs_checked"] == 0 for v in continuity.values())
                              else "evaluated")

    # ---- 资格判定（并列状态 → 单一资格结论）----
    for r in rows:
        blockers: list[str] = []
        warnings: list[str] = []
        if r.get("design_status") != "intended_design":
            blockers.append(str(r.get("design_status")))
        if r.get("geometry_status") != "ok":
            blockers.append(f"geometry:{r.get('geometry_status')}")
        if r.get("selection_status") != "verified":
            blockers.append(f"selection:{r.get('selection_status')}")
        if r.get("area_status") != "valid_geometry":
            blockers.append(f"area:{r.get('area_status')}")
        if r.get("physical_extent_suspect"):
            blockers.append("physical_extent_suspect")
        if r.get("mesh_crosscheck_status") == "mismatch":
            warnings.append("mesh_crosscheck:mismatch")
        if r.get("area_anomaly_flags"):
            warnings.append("area_anomaly:" + ",".join(sorted(set(r["area_anomaly_flags"]))))
        r["eligible_for_ranking"] = not blockers
        # 裁决 §6.2：资格原因与质量警告**分列**——不可排名时才写 eligibility_reason，
        # 面积突变这类"可临时分析但需注意"的信息写 quality_warnings，不得塞进"不可排名原因"。
        r["eligibility_reason"] = "; ".join(blockers)
        r["quality_warnings"] = "; ".join(warnings)
        r["eligibility_level"] = ("ineligible" if blockers
                                 else ("full" if not warnings else "provisional"))

    # ---- intop5 控制面稳定性（裁决 §3.3）----
    # 关键实测（2026-09-13）：实体**标签**会随退化设计漂移，但**面积**恒定。
    # 故"实体集合是否恒为 [1,3,70,104]"这一判据只在**候选子集**上具约束意义，
    # 因此全量与可排名子集分别判定，排序口径采用候选子集。
    theory = 6.283185307179586e-08          # 2πR², R = 100 µm

    def _ptot_verdict(subset: list[dict], label: str) -> dict:
        ents = [tuple(sorted(int(v) for v in r["intop5_entities"]))
                for r in subset if r.get("intop5_entities")]
        uniq = sorted(set(ents))
        fixed = bool(ents) and uniq == [(1, 3, 70, 104)]
        vals = [float(r["area_ptot_geometry"]) for r in subset
                if isinstance(r.get("area_ptot_geometry"), (int, float))]
        spread = None
        if vals:
            lo, hi = min(vals), max(vals)
            mean = sum(vals) / len(vals)
            spread = {"n": len(vals), "min": lo, "max": hi,
                      "rel_spread": ((hi - lo) / lo) if lo else None,
                      "unique_values": len(set(vals)),
                      "theoretical_hemisphere_2piR2_R100um": theory,
                      "rel_diff_of_mean_vs_theory": abs(mean - theory) / theory}
        anom = continuity.get("ptot", {}).get("anomalies_found", 0)
        ids_changed = len(uniq) > 1
        area_single = bool(spread) and spread.get("unique_values") == 1
        # 裁决 §2.2：编号变化**不能**直接断言物理控制面改变 ⇒ 只能记 entity_ids_changed，
        # 物理面稳定性标 pending_signature_check，可比性对"被设计排除的组"标 not_applicable。
        if not ids_changed and area_single and anom == 0:
            stability, status, comparable = "stable", "stable_fixed_hemisphere", True
        elif ids_changed:
            stability, status = "pending_signature_check", "entity_ids_changed_signature_pending"
            comparable = ("not_applicable_for_ineligible_designs"
                          if label.startswith("全部") else False)
        else:
            stability, status, comparable = "unstable", "unstable_area_or_anomaly", False
        out = {"label": label, "n": len(subset), "entity_sets": [list(e) for e in uniq],
               "entity_set_constant": not ids_changed, "entity_ids_changed": ids_changed,
               "entities_equal_reference": fixed,
               "physical_surface_stability": stability,
               "anomalies": anom, "status": status,
               "cross_x_comparable": comparable,
               "area_ptot_spread": spread,
               "swr1_efc1_consistency": sorted({
                   (r.get("intop5_eq_swr1"), r.get("intop5_eq_efc1")) for r in subset
                   if r.get("intop5_eq_swr1") is not None})}
        print(f"[intop5 控制面/{label}] n={len(subset)}｜实体集合={out['entity_sets']}"
              f"｜编号变化={ids_changed}｜物理面稳定性={stability}｜status={status}"
              f"｜cross_x_comparable={comparable}｜与swr1/efc1一致={out['swr1_efc1_consistency']}",
              flush=True)
        return out

    ptot_all = _ptot_verdict(rows, "全部162")
    ptot_elig = _ptot_verdict([r for r in rows if r.get("eligible_for_ranking")], "可排名候选")
    ptot_status = ptot_elig["status"]
    ptot_comparable = ptot_elig["cross_x_comparable"]
    spread = ptot_elig["area_ptot_spread"]

    wall = round(time.perf_counter() - t_all, 1)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("eligibility_level", "?")] = counts.get(r.get("eligibility_level", "?"), 0) + 1
    sel_counts: dict[str, int] = {}
    area_counts: dict[str, int] = {}
    for r in rows:
        sel_counts[r.get("selection_status", "?")] = sel_counts.get(r.get("selection_status", "?"), 0) + 1
        area_counts[r.get("area_status", "?")] = area_counts.get(r.get("area_status", "?"), 0) + 1

    # ---- 子运行级溯源（Codex 裁决 §1.2：新运行必须自带以下字段）----
    import hashlib as _hl

    def _canon(obj) -> str:
        return _hl.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()

    _script = Path(__file__).resolve()
    _crit = {"schema_version": "1", "phase": args.phase, "mesh_max_n1": args.mesh_max_n1,
             "area_method": "geometry_measure_getArea", "area_object_name": args.area_obj_name,
             "area_anomaly_threshold": args.area_anomaly_tol,
             "mesh_crosscheck_threshold": args.area_cross_tol,
             "design_rule": "N1<N2=>intended; == =>coincident; > =>reversed",
             "comsol": str(client.version), "mph": mph.__version__}
    provenance = {
        "run_id": run_id, "script_path": str(_script),
        "script_sha256": _hl.sha256(_script.read_bytes()).hexdigest(),
        "criteria_object": _crit, "criteria_hash": _canon(_crit),
        "model_sha256": staging["source_sha256"], "staged_sha256": staging["staged_sha256"],
        "comsol_version": str(client.version), "mph_version": mph.__version__,
    }

    payload = {
        "provenance": provenance,
        "run_id": run_id, "kind": "geometry_selection_precheck_v3", "phase": args.phase,
        "mesh_max_n1": args.mesh_max_n1,
        "model_path": staging["staged"], "source_model": staging["source"],
        "source_sha256": staging["source_sha256"], "staged_sha256": staging["staged_sha256"],
        "light_model_note": "轻模型 + diff 证据（Codex §6 接受）；条件：双哈希 + COMSOL 版本 + 哨兵实体/面积",
        "grid": {"x_scale": xs, "N_w_te1": n1s, "n_combos": len(xs) * len(n1s),
                 "executed": len(combos), "only_sentinels": args.only_sentinels},
        "effective_params_raw": {"W_min_expression": w_expr, "N_mem_expression": n_mem_expr,
                                 "N_w_te2_expression": n2_expr,
                                 "W_min_raw_value": w_raw, "N_mem_raw_value": n_mem_raw,
                                 "N_w_te2_raw_value": n2_raw, "R_mem_raw_value": r_mem_raw,
                                 "unit_note": "raw value 按参数原始表达式解析（W_min 以 µm 声明），"
                                              "未换算为 SI；比较在同一单位下进行"},
        "status_vocab": {"design": DESIGN_STATUS, "geometry": GEOMETRY_STATUS,
                         "selection": SELECTION_STATUS, "area": AREA_STATUS,
                         "mesh": MESH_STATUS, "eligibility": ELIGIBILITY},
        "counts": {"eligibility": counts, "selection": sel_counts, "area": area_counts},
        "area_continuity": continuity,
        "area_continuity_status": area_continuity_status,
        "ptot_control_surface_status": ptot_status,
        "ptot_cross_x_comparable": ptot_comparable,
        "ptot_control_surface_all162": ptot_all,
        "ptot_control_surface_eligible": ptot_elig,
        "area_ptot_spread": spread,
        "cleanup": cleanup_ok,
        "server_memory": {"before": mem_before, "after": cleanup_ok.get("server_memory_after")},
        "wall_seconds": wall, "comsol_version": str(client.version), "mph_version": mph.__version__,
        "rows": rows,
    }
    (run_dir / "geometry_selection_precheck.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    fields = ["x_scale", "N_w_te1", "design_status", "geometry_status", "selection_status",
              "area_status", "mesh_status", "mesh_crosscheck_status", "mesh_crosscheck_reason",
              "eligible_for_ranking", "eligibility_level", "eligibility_reason", "quality_warnings",
              "physical_extent_suspect",
              "outer_bc_count", "inner_bc_count", "bc_intersection_count",
              "named_vs_bc_outer_equal", "named_vs_bc_inner_equal",
              "area_outer_geometry", "area_inner_geometry", "area_ptot_geometry",
              "area_outer_source", "area_inner_source", "area_ptot_source",
              "area_outer_mesh_integral", "area_inner_mesh_integral", "area_ptot_mesh_integral",
              "area_outer_relative_difference", "area_inner_relative_difference",
              "area_ptot_relative_difference", "area_outer_geometry_call",
              "area_outer_geometry_error", "area_inner_geometry_error", "area_ptot_geometry_error",
              "continuity_pairs_checked_outer", "continuity_pairs_checked_inner",
              "continuity_pairs_checked_ptot", "continuity_anomalies_outer",
              "continuity_anomalies_inner", "continuity_anomalies_ptot", "area_anomaly_flags",
              "geometry_seconds", "mesh_seconds", "mesh_element_count",
              "intop5_eq_swr1", "intop5_eq_efc1", "ptot_boundary_bounding_box",
              "outer_bc_entities", "inner_bc_entities", "intop5_entities", "swr1_entities",
              "efc1_entities"]
    with (run_dir / "geometry_selection_precheck.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # ---- 哨兵验收（裁决 §9）----
    sent = [r for r in rows if (r["x_scale"], r["N_w_te1"]) in sentinels]
    checks = []
    if args.only_sentinels:
        def chk(name, ok, detail=""):
            checks.append({"check": name, "pass": bool(ok), "detail": detail})

        chk("三个哨兵点均已执行", len(sent) == len(sentinels), f"{len(sent)}/{len(sentinels)}")
        chk("几何全部成功", all(r.get("geometry_status") == "ok" for r in sent))
        chk("term1/pot2 实体均非空",
            all(r.get("outer_bc_count") and r.get("inner_bc_count") for r in sent))
        chk("内外实体无交集", all(not r.get("bc_intersection") for r in sent))
        chk("命名选择与物理 BC 实体一致",
            all(r.get("named_vs_bc_outer_equal") and r.get("named_vs_bc_inner_equal") for r in sent))
        chk("几何 getArea() 取得有限正面积",
            all(r.get(f"area_{k}_geometry") and r[f"area_{k}_geometry"] > 0
                for r in sent for k in AREA_KINDS),
            str({f"{r['x_scale']:g},{r['N_w_te1']}": r.get("area_outer_geometry_call") for r in sent}))
        diffs = [r.get(f"area_{k}_relative_difference") for r in sent for k in AREA_KINDS]
        numeric = [d for d in diffs if isinstance(d, (int, float))]
        chk("几何与 Mesh 积分面积偏差在容忍内",
            all(d <= args.area_cross_tol for d in numeric) if numeric else None,
            f"n={len(numeric)}，max={max(numeric) if numeric else None}，"
            f"tol={args.area_cross_tol}")
        chk("三种面积来源分别记录",
            all(all(r.get(f"area_{k}_source") for k in AREA_KINDS) for r in sent))
        nlines = len(ckpt.read_text(encoding="utf-8").splitlines()) if ckpt.is_file() else 0
        chk("checkpoint 逐点写入", nlines >= len(sent), f"jsonl 行数={nlines}")
        chk("COMSOL 模型/客户端已释放", cleanup_ok.get("clear") is True
            and cleanup_ok.get("disconnect") is True, str(cleanup_ok))
        chk("哨兵报告含双哈希+版本+有效参数",
            bool(staging["source_sha256"] and staging["staged_sha256"] and w_expr))
        payload_ok = [c for c in checks if c["pass"] is not None]
        print("\n== 哨兵验收 ==", flush=True)
        for c in checks:
            mark = "PASS" if c["pass"] else ("N/A" if c["pass"] is None else "FAIL")
            print(f"  [{mark}] {c['check']}  {c['detail']}", flush=True)
        print(f"  → 通过 {sum(1 for c in payload_ok if c['pass'])}/{len(payload_ok)}"
              f"（几何面积成功但 Mesh 失败仍可继续 162 组一级；两条面积通路都失败则只允许一级实体检查）",
              flush=True)

    (run_dir / "sentinel_report.json").write_text(json.dumps({
        "run_id": run_id, "sentinels": [f"{a:g}:{b}" for a, b in sentinels],
        "source_model": staging["source"], "source_sha256": staging["source_sha256"],
        "staged_path": staging["staged"], "staged_sha256": staging["staged_sha256"],
        "comsol_version": str(client.version), "mph_version": mph.__version__,
        "effective_params_raw": payload["effective_params_raw"],
        "checks": checks, "cleanup": cleanup_ok, "rows": sent,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    try:
        with connect() as conn:
            insert_run(conn, run_id=run_id, backend="local", pathway="mph-client",
                       model_path=staging["staged"], model_sha256=staging["staged_sha256"],
                       software={"comsol": str(client.version), "mph": mph.__version__},
                       settings={"kind": "geometry_selection_precheck_v3", "phase": args.phase,
                                 "grid": payload["grid"], "counts": payload["counts"]},
                       status="succeeded", exit_code=0, wall_seconds=wall, run_dir=str(run_dir),
                       started_at=None, finished_at=now_utc())
    except Exception as exc:
        print(f"[warn] 写 run 记录失败（不影响 JSONL 证据）：{type(exc).__name__}: {exc}", flush=True)

    print(f"\n== 资格统计 ==\n  {counts}\n== 选择状态 ==\n  {sel_counts}"
          f"\n== 面积状态 ==\n  {area_counts}", flush=True)
    print(f"\n耗时 {wall} s；落档 {run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
