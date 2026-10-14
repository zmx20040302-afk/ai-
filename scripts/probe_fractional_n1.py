# -*- coding: utf-8 -*-
"""最小实证：目标 PMUT 模型能否接受**小数 N1**（`N_w_te1`），以及它的几何/选择集怎么变。

背景：预注册 `work/runs/multichannel-surrogate-v2-20261001/PREREG_multichannel_surrogate_v2.md`
§2 要求先做这次实证，用来判定 v2 走 **A 可验证分支** 还是 **B 趋势分支**。
用户 2026-10-01 批准，并指定模型用**库内逐字节副本**
`work/models/b_GE_task3_2new_legacy_1ohm_drive_v1.mph`（sha256 `0f75ca1d…`，103,681,444 B；
与 M0 母版 `b_GE_task3_2new.mph` 逐字节相同、`change_log` 为空 ⇒ 几何未改）。

**只做几何 + 网格 + 选择集，不做物理求解**：要回答的是"小数 N1 在几何上是否成立、
物理含义是连续缩放还是整数指条"，几何层就能定，不必吃求解算力。

判据（写死，跑完照此判定，不许事后改）：
* `.5` 上 `geom.run()` 成功且 `cyl3`/`cyl9` 选择集**非空**、且与整数点**同量级** ⇒ 记 `supported`，
  v2 走 A 分支（可以在小数 N1 上真跑 COMSOL 做留出集）；
* `.5` 上几何失败、或选择集为空/退化 ⇒ 记 `unsupported`，v2 走 B 分支（仅趋势，标注不可制造/未验证）；
* 任何一步失败都**如实记录**，不粉饰、不改口径。

用法：
    work\\.venv\\Scripts\\python.exe scripts\\probe_fractional_n1.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
COMSOL_BIN = Path(COMSOL_HOME) / "bin" / "win64"
SRC = REPO / "work/models/b_GE_task3_2new_legacy_1ohm_drive_v1.mph"
RUN_DIR = REPO / "work/runs/fractional-n1-probe-20261001"
OUT = RUN_DIR / "fractional_n1_probe.json"
#: 对照点：4 与 5 是整数基线，4.5 是要验的小数点（N2=6 层内 N1∈{1..5}）
POINTS = [4.0, 4.5, 5.0]
N2 = 6.0
#: 需要核对实体数的选择集（来自 .m 证据：cyl3/cyl9 的半径含 N_w_te1）
SELECTIONS = ("cyl3", "cyl9")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def probe(label, fn, ev):
    """执行一步；失败只记录，不中断（局部失败不掩盖已达成的结论）。"""
    t0 = time.perf_counter()
    try:
        v = fn()
        ev["steps"].append("%s: OK (%.2fs)" % (label, time.perf_counter() - t0))
        return v
    except Exception as exc:  # noqa: BLE001
        ev["errors"].append("%s: %s: %s" % (label, type(exc).__name__, exc))
        ev["steps"].append("%s: FAILED" % label)
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="小数 N1 最小实证（几何/选择集，不求解）")
    ap.add_argument("--model", default=str(SRC))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--timeout", type=float, default=1800.0)
    a = ap.parse_args(argv)

    os.environ["PATH"] = "%s%s%s" % (COMSOL_BIN, os.pathsep, os.environ.get("PATH", ""))
    os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(a.model)
    ev: dict = {
        "kind": "fractional_n1_probe",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "question": "目标 PMUT 模型能否接受小数 N_w_te1？几何/选择集如何变化？",
        "prereg": "work/runs/multichannel-surrogate-v2-20261001/PREREG_multichannel_surrogate_v2.md",
        "source_model": {"path": str(src), "exists": src.is_file()},
        "points": POINTS, "n2": N2, "selections": list(SELECTIONS),
        "solved_physics": False,
        "verdict": None, "steps": [], "errors": [], "per_point": {},
    }
    if not src.is_file():
        ev["errors"].append("源模型不存在：%s" % src)
        Path(a.out).write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[FAIL] 源模型不存在"); return 2
    ev["source_model"]["bytes"] = src.stat().st_size
    ev["source_model"]["sha256"] = sha256(src)

    # 只读复制到本次 run 目录（生产/母版一律只读引用；AGENTS.md §4）
    work = RUN_DIR / "model_copy.mph"
    if not work.is_file() or sha256(work) != ev["source_model"]["sha256"]:
        shutil.copy2(src, work)
    ev["working_copy"] = {"path": str(work.relative_to(REPO)), "sha256": sha256(work)}

    try:
        import mph
        ev["mph_version"] = getattr(mph, "__version__", "unknown")
        t0 = time.perf_counter()
        # MPh 在没有服务时会自行拉起一个（PATH 已含 COMSOL bin）
        client = probe("启动/连接 mphserver", lambda: mph.Client(), ev)
        if client is None:
            raise RuntimeError("无法取得 mph 客户端")
        ev["client_version"] = str(client.version)
        ev["client_start_seconds"] = round(time.perf_counter() - t0, 2)

        model = probe("加载模型副本", lambda: client.load(str(work)), ev)
        if model is None:
            raise RuntimeError("模型加载失败")
        ev["parameters_initial"] = probe(
            "读初始参数", lambda: {k: str(v) for k, v in model.parameters().items()}, ev)

        for n1 in POINTS:
            tag = "N1=%g" % n1
            rec: dict = {"n1": n1, "n2": N2}
            rec_local = rec
            probe("%s 写入 N_w_te1" % tag,
                  lambda n1=n1: model.parameter("N_w_te1", "%g" % n1), ev)
            rec["param_readback"] = probe(
                "%s 回读" % tag, lambda: str(model.parameters().get("N_w_te1")), ev)

            # MPh 1.4 的 Model **没有** geometry() 访问器（只有 geometries()/mesh()），
            # 所以几何/网格/选择集都做**多路回退**，并记录**哪条路成功**——
            # 不猜 API 是否存在（AGENTS.md：判"某 API 不存在"必须查到接口层再下结论）。
            def _try_chain(label, fns):
                errs = []
                for name, fn in fns:
                    try:
                        return {"via": name, "result": fn()}
                    except Exception as exc:  # noqa: BLE001
                        errs.append("%s -> %s: %s" % (name, type(exc).__name__, exc))
                ev["errors"].append("%s：所有尝试都失败：%s" % (label, " | ".join(errs)))
                return None

            def _geom():
                return _try_chain("%s 重建几何" % tag, [
                    ("java.geom('geom1').run()",
                     lambda: (model.java.geom("geom1").run(), "ok")[1]),
                    ("java.component('comp1').geom('geom1').run()",
                     lambda: (model.java.component("comp1").geom("geom1").run(), "ok")[1]),
                    ("model.geometry('geom1').run()",
                     lambda: (model.geometry("geom1").run(), "ok")[1]),
                ])
            rec["geometry"] = probe("%s 重建几何" % tag, _geom, ev)

            def _sel(name):
                return _try_chain("%s 选择集 %s" % (tag, name), [
                    ("java.component('comp1').selection(%r).entities()" % name,
                     lambda: [int(x) for x in
                              model.java.component("comp1").selection(name).entities()]),
                    ("java.selection(%r).entities()" % name,
                     lambda: [int(x) for x in model.java.selection(name).entities()]),
                ])
            rec["selections"] = {}
            for sname in SELECTIONS:
                got = probe("%s 选择集 %s" % (tag, sname), lambda s=sname: _sel(s), ev)
                if isinstance(got, dict):
                    ents = got.get("result") or []
                    rec["selections"][sname] = {"via": got.get("via"),
                                                "n_entities": len(ents),
                                                "entities_head": ents[:12]}
                    print("    %s %s: n_entities=%d via=%s"
                          % (tag, sname, len(ents), got.get("via")), flush=True)
                else:
                    rec["selections"][sname] = None

            def _mesh():
                # ⚠️ 实测教训（2026-10-01）：`model.java.mesh('mesh1').run()` 在序列**不存在**时
                # **不抛异常**（只往 stderr 打一句），于是"没抛异常"被当成通过 ⇒ 假通过。
                # 现在的判据：先枚举 `model.meshes()` 拿**真实名字**，再要求能读到**单元数**。
                names = []
                try:
                    names = [str(x) for x in model.meshes()]
                except Exception as exc:  # noqa: BLE001
                    ev["errors"].append("%s 枚举网格序列失败：%s: %s" % (tag, type(exc).__name__, exc))
                rec_local["mesh_names"] = names
                if not names:
                    ev["errors"].append("%s 模型里没有网格序列 ⇒ 网格无法验证" % tag)
                    return None
                name = names[0]

                def _mk(node):
                    def run_and_stat():
                        node.run()
                        st = node.stat()
                        n = None
                        for meth in ("getNumElem", "getNumElements", "numElem"):
                            f = getattr(st, meth, None)
                            if callable(f):
                                n = int(f())
                                break
                        if n is None:      # 读不到单元数 ⇒ 视为未验证，而不是"大概成功"
                            raise RuntimeError("拿不到单元数（stat=%r）⇒ 网格未验证" % (st,))
                        return {"mesh": name, "n_elem": n}
                    return run_and_stat

                # 逐层级尝试（实测：`java.mesh(...)` 会报"未知网格"，网格挂在组件下）
                cands = []
                for tag in ("mesh1", name):
                    cands.append(("java.component('comp1').mesh(%r).run()+stat" % tag,
                                  lambda t=tag: _mk(model.java.component("comp1").mesh(t))))
                    cands.append(("java.mesh(%r).run()+stat" % tag,
                                  lambda t=tag: _mk(model.java.mesh(t))))
                return _try_chain("%s 生成网格(%s)" % (tag, name),
                                  [(lbl, fn()) for lbl, fn in cands])
            rec["mesh"] = probe("%s 生成网格" % tag, _mesh, ev)
            print("    %s mesh=%s" % (tag, json.dumps(rec["mesh"], ensure_ascii=False)[:120]),
                  flush=True)
            ev["per_point"][tag] = rec
            print("  - %s: geom=%s sel=%s" % (
                tag, (rec["geometry"] or {}).get("via"),
                {k: ((v or {}).get("n_entities")) for k, v in rec["selections"].items()}),
                flush=True)

        # ---- 判据（预注册 §2/§6，跑完照此判，不许事后改）----
        frac = ev["per_point"].get("N1=4.5") or {}
        ints = [ev["per_point"].get("N1=4") or {}, ev["per_point"].get("N1=5") or {}]
        ok_geom = bool(frac.get("geometry"))
        sel_ok = all(
            isinstance(frac.get("selections", {}).get(s), dict)
            and (frac["selections"][s] or {}).get("n_entities", 0) > 0 for s in SELECTIONS)
        int_ok = all(bool(i.get("geometry")) for i in ints)
        ev["criteria"] = {"frac_geometry_ok": ok_geom, "frac_selections_nonempty": sel_ok,
                          "integer_baselines_ok": int_ok,
                          "frac_mesh_ok": bool((frac.get("mesh") or {}).get("result"))}
        if ok_geom and sel_ok:
            ev["verdict"] = "supported"
            ev["verdict_note"] = ("小数 N1 在几何上成立且选择集非空 ⇒ v2 可走 **A 可验证分支**；"
                                  "'是否等价于半根电极'仍须看实体数对比，见 per_point")
        elif not ok_geom:
            ev["verdict"] = "unsupported"
            ev["verdict_note"] = "小数 N1 上几何无法重建 ⇒ 按预注册 §6 落 B 分支（仅趋势）"
        else:
            ev["verdict"] = "inconclusive"
            ev["verdict_note"] = "几何可重建但选择集为空/退化 ⇒ 证据不足以支持 A 分支"
        ev["ok"] = True
    except Exception as exc:  # noqa: BLE001
        ev["errors"].append("fatal: %s: %s" % (type(exc).__name__, exc))
        ev["traceback"] = traceback.format_exc()

    Path(a.out).write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 70)
    print("小数 N1 最小实证：ok=%s verdict=%s" % (ev.get("ok"), ev.get("verdict")))
    for s in ev["steps"]:
        print("  -", s)
    for e in ev["errors"]:
        print("  [错误]", e)
    print("证据：", a.out)
    print("=" * 70)
    return 0 if ev.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
