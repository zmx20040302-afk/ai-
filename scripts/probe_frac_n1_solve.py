# -*- coding: utf-8 -*-
"""小数 N1 第二步：枚举真实结构 → 建网格 → 在 N1=4.5 上做**一次真求解**。

承接 `scripts/probe_fractional_n1.py`（那一步已证明：N1=4/4.5/5 几何都能重建、
选择集实体数一致 ⇒ 几何层面支持小数 N1），本脚本回答预注册 §5 的 **A 分支**问题：
**小数 N1 能不能真的解出来**（不是几何能不能建）。

做法上刻意"先看再动"（不猜 API）：
1. **枚举**组件/几何/网格/研究的真实 tag —— 上一步 `java.mesh('mesh1')` 报"未知网格"，
   而 `.m` 里确实写着 `component('comp1').mesh('mesh1')` ⇒ 需要先看这份 .mph **到底存了什么**；
2. 几何重建（上一步已验证过）；
3. 网格：有 `mesh1` 就跑；**没有就按 COMSOL 默认创建**（并如实记录"是我们建的"）；
4. `std1` 真求解。**注意：不做进程内硬超时** —— COMSOL 的 Java 求解一旦开始，
   从同一进程里安全中断是做不到的（强杀会留下半个求解状态）。所以：
   * 求解前**禁用 `std1` 里的参数化/批处理特征**，保证只解**一个点**（否则会变成一整轮扫描）；
   * 真正的超时保护交给**外部作业**（我按后台作业跑，必要时由人中止）。

用法：
    work\\.venv\\Scripts\\python.exe scripts\\probe_frac_n1_solve.py --n1 4.5
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


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def step(label, fn, ev):
    t0 = time.perf_counter()
    try:
        v = fn()
        ev["steps"].append("%s: OK (%.2fs)" % (label, time.perf_counter() - t0))
        return v
    except Exception as exc:  # noqa: BLE001
        ev["errors"].append("%s: %s: %s" % (label, type(exc).__name__, str(exc)[:300]))
        ev["steps"].append("%s: FAILED" % label)
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="小数 N1：枚举 + 网格 + 一次真求解")
    ap.add_argument("--model", default=str(SRC))
    ap.add_argument("--n1", type=float, default=4.5)
    ap.add_argument("--n2", type=float, default=6.0)
    ap.add_argument("--timeout", type=float, default=1500.0)
    ap.add_argument("--out", default=str(RUN_DIR / "fractional_n1_solve.json"))
    a = ap.parse_args(argv)

    os.environ["PATH"] = "%s%s%s" % (COMSOL_BIN, os.pathsep, os.environ.get("PATH", ""))
    os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    src = Path(a.model)
    ev: dict = {
        "kind": "fractional_n1_solve_probe",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "question": "小数 N1 能否真的被求解（预注册 §5 A 分支的准入条件）",
        "prereg": "work/runs/multichannel-surrogate-v2-20261001/PREREG_multichannel_surrogate_v2.md",
        "n1": a.n1, "n2": a.n2, "solve_timeout_s": a.timeout,
        "source_model": {"path": str(src), "exists": src.is_file()},
        "steps": [], "errors": [], "verdict": None,
    }
    if not src.is_file():
        ev["errors"].append("源模型不存在：%s" % src)
        Path(a.out).write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2
    ev["source_model"]["sha256"] = sha256(src)
    ev["source_model"]["bytes"] = src.stat().st_size

    work = RUN_DIR / ("solve_copy_N1_%g.mph" % a.n1)
    shutil.copy2(src, work)
    ev["working_copy"] = str(work.relative_to(REPO))

    try:
        import mph
        client = step("启动/连接 mphserver", lambda: mph.Client(), ev)
        if client is None:
            raise RuntimeError("无 mph 客户端")
        ev["client_version"] = str(client.version)
        model = step("加载模型副本", lambda: client.load(str(work)), ev)
        if model is None:
            raise RuntimeError("加载失败")
        J = model.java

        # ---- 1 枚举真实结构（不猜）----
        ev["structure"] = {
            "components": step("组件 tags", lambda: [str(x) for x in J.component().tags()], ev),
            "geoms": step("几何 tags",
                          lambda: [str(x) for x in J.component("comp1").geom().tags()], ev),
            "meshes": step("网格 tags",
                           lambda: [str(x) for x in J.component("comp1").mesh().tags()], ev),
            "component_meshes_global": step("全局网格 tags",
                                            lambda: [str(x) for x in J.mesh().tags()], ev),
            "studies": step("研究 tags", lambda: [str(x) for x in J.study().tags()], ev),
            "mph_meshes": step("MPh 视角 meshes()", lambda: [str(x) for x in model.meshes()], ev),
        }

        # ---- 2 设参数 + 几何 ----
        step("写入 N_w_te1=%g" % a.n1,
             lambda: model.parameter("N_w_te1", "%g" % a.n1), ev)
        step("写入 N_w_te2=%g" % a.n2,
             lambda: model.parameter("N_w_te2", "%g" % a.n2), ev)
        ev["readback"] = step("回读 N_w_te1",
                              lambda: str(model.parameters().get("N_w_te1")), ev)
        step("重建几何", lambda: J.component("comp1").geom("geom1").run(), ev)

        # ---- 3 网格：有就跑；没有再按默认创建（如实记录是谁建的）----
        def _mesh():
            comp = J.component("comp1")
            tags = [str(x) for x in comp.mesh().tags()]
            if not tags:
                comp.mesh().create("mesh1")
                ev["mesh_created_by_probe"] = True
                tag = "mesh1"
            else:
                ev["mesh_created_by_probe"] = False
                tag = tags[0]
            comp.mesh(tag).run()
            st = comp.mesh(tag).stat()
            n = None
            for meth in ("getNumElem", "getNumElements", "numElem"):
                f = getattr(st, meth, None)
                if callable(f):
                    n = int(f()); break
            if n is None:
                raise RuntimeError("网格已 run 但读不到单元数（stat=%r）" % (st,))
            return {"tag": tag, "n_elem": n}
        ev["mesh"] = step("生成网格", _mesh, ev)

        # ---- 4 真求解（带硬超时）----
        studies = ev["structure"].get("studies") or []
        if not studies:
            raise RuntimeError("模型里没有研究（study）可求解")
        sname = studies[0]
        ev["solving_study"] = sname

        def _prep_study():
            """禁用参数化/批处理特征 ⇒ 只解**一个点**（否则会跑一整轮扫描）。"""
            st = J.study(sname)
            feats = [str(x) for x in st.feature().tags()]
            disabled = []
            for f in feats:
                node = st.feature(f)
                try:
                    t = str(node.getType())
                except Exception:  # noqa: BLE001
                    t = ""
                if ("Parametric" in t) or ("Batch" in t):
                    try:
                        node.active(False)
                        disabled.append({"feature": f, "type": t})
                    except Exception as exc:  # noqa: BLE001
                        ev["errors"].append("禁用 %s 失败：%s" % (f, exc))
            return {"features": feats, "disabled": disabled}
        ev["study_prep"] = step("禁用参数化特征（只解一个点）", _prep_study, ev)

        t0 = time.perf_counter()
        try:
            J.study(sname).run()
            ev["solve_seconds"] = round(time.perf_counter() - t0, 1)
            ev["solve_ok"] = True
        except Exception as exc:  # noqa: BLE001
            ev["solve_seconds"] = round(time.perf_counter() - t0, 1)
            ev["solve_ok"] = False
            ev["solve_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])

        # ---- 5 判据 ----
        geom_ok = any(s.startswith("重建几何: OK") for s in ev["steps"])
        mesh_ok = isinstance(ev.get("mesh"), dict)
        if geom_ok and mesh_ok and ev.get("solve_ok"):
            ev["verdict"] = "solvable"
            ev["verdict_note"] = ("小数 N1=%g 能建几何、能建网格、能求解 ⇒ v2 可走 **A 可验证分支**；"
                                  "下一步是取工程量/场与 COMSOL 留出集比对。" % a.n1)
        elif geom_ok and mesh_ok:
            ev["verdict"] = "geometry_and_mesh_only"
            ev["verdict_note"] = ("几何与网格通过，但**求解未成功**（见 solve_error）"
                                  "⇒ A 分支尚未打开，如实记，不往下推。")
        else:
            ev["verdict"] = "unsupported"
            ev["verdict_note"] = "几何或网格未通过 ⇒ 按预注册 §6 落 B 分支（仅趋势）。"
        ev["ok"] = True
    except Exception as exc:  # noqa: BLE001
        ev["errors"].append("fatal: %s: %s" % (type(exc).__name__, exc))
        ev["traceback"] = traceback.format_exc()

    Path(a.out).write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 70)
    print("小数 N1 求解探针：n1=%g verdict=%s solve_ok=%s"
          % (a.n1, ev.get("verdict"), ev.get("solve_ok")))
    print("  结构:", json.dumps(ev.get("structure"), ensure_ascii=False)[:400])
    print("  网格:", json.dumps(ev.get("mesh"), ensure_ascii=False))
    print("  求解: %.1fs" % (ev.get("solve_seconds") or -1))
    for e in ev["errors"]:
        print("  [错误]", e[:200])
    print("证据：", a.out)
    print("=" * 70)
    return 0 if ev.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
