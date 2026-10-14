# -*- coding: utf-8 -*-
"""小数 N1 第 1 步：多点求解 + 每点取一个**工程量**（域内 max|p|）。

承接 `scripts/probe_frac_n1_solve.py`（已证明 N1=4.5 能建几何/建网格/求解，106 s）。
本脚本在**若干个小数 N1** 上重复，为预注册 §5 的 A 分支准备**独立留出集**。

每点记录（取不到就写 null 并记 error，**不编数字**）：
* 几何 / 网格（tag、单元数）/ 求解（秒数、是否无异常）；
* **工程量**：域内 `max|p|`（声压幅值）——用 MPh 的 `evaluate` 尝试；尝试失败即记失败；
* 求解前禁用 `std1` 的参数化特征（保证一个点一次解，不是一整轮扫描）。

⚠️ 不做进程内硬超时（COMSOL Java 求解无法从同进程安全中断）；超时保护交给外部作业。
⚠️ `solve_ok=True` 只表示**没有抛异常**，不代表已核收敛——收敛核对另做，别把它读成"已验证"。

用法：
    work\\.venv\\Scripts\\python.exe scripts\\probe_frac_n1_multipoint.py --n1s 4.5,5.5,6.5
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
EXPR = "p"          # 声压（Pa）；取域内最大值作为工程量
FALLBACK_EXPRS = ("p", "acpr.p", "p_abs", "abs(p)")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def step(label, fn, ev):
    t0 = time.perf_counter()
    try:
        v = fn()
        ev["steps"].append("%s: OK (%.2fs)" % (label, time.perf_counter() - t0))
        return v
    except Exception as exc:  # noqa: BLE001
        ev["errors"].append("%s: %s: %s" % (label, type(exc).__name__, str(exc)[:240]))
        ev["steps"].append("%s: FAILED" % label)
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="小数 N1 多点求解 + 每点一个工程量")
    ap.add_argument("--model", default=str(SRC))
    ap.add_argument("--n1s", default="4.5,5.5,6.5")
    ap.add_argument("--n2", type=float, default=6.0)
    ap.add_argument("--out", default=str(RUN_DIR / "fractional_n1_multipoint.json"))
    a = ap.parse_args(argv)
    n1s = [float(x) for x in str(a.n1s).split(",") if x.strip()]

    os.environ["PATH"] = "%s%s%s" % (COMSOL_BIN, os.pathsep, os.environ.get("PATH", ""))
    os.environ.setdefault("COMSOL_HOME", COMSOL_HOME)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    src = Path(a.model)
    ev: dict = {
        "kind": "fractional_n1_multipoint",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "预注册 §5 A 分支：小数 N1 的独立留出集（每点一个工程量）",
        "prereg": "work/runs/multichannel-surrogate-v2-20261001/PREREG_multichannel_surrogate_v2.md",
        "expr": EXPR, "n2": a.n2, "n1s": n1s,
        "source_model": {"path": str(src), "exists": src.is_file()},
        "steps": [], "errors": [], "per_point": {}, "ok": False,
        "caveat": "solve_ok 只表示未抛异常；收敛与场合理性**尚未核对**，不得读作已验证。",
    }
    if not src.is_file():
        Path(a.out).write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[FAIL] 源模型不存在"); return 2
    ev["source_model"]["sha256"] = sha256(src)
    ev["source_model"]["bytes"] = src.stat().st_size

    work = RUN_DIR / "multipoint_copy.mph"
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
        ev["eval_api"] = [m for m in dir(mph.Model) if "eval" in m.lower()]

        # 禁用参数化/批处理（一次一点）
        st_tags = [str(x) for x in J.study().tags()]
        sname = st_tags[0]
        ev["solving_study"] = sname

        def _prep():
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
                    node.active(False)
                    disabled.append({"feature": f, "type": t})
            return {"features": feats, "disabled": disabled}
        ev["study_prep"] = step("禁用参数化特征", _prep, ev)

        for n1 in n1s:
            tag = "N1=%g" % n1
            rec: dict = {"n1": n1, "n2": a.n2}
            step("%s 写 N_w_te1" % tag, lambda n1=n1: model.parameter("N_w_te1", "%g" % n1), ev)
            step("%s 写 N_w_te2" % tag, lambda: model.parameter("N_w_te2", "%g" % a.n2), ev)
            rec["readback"] = step("%s 回读" % tag,
                                   lambda: str(model.parameters().get("N_w_te1")), ev)
            rec["geometry_ok"] = step(
                "%s 重建几何" % tag,
                lambda: (J.component("comp1").geom("geom1").run(), True)[1], ev) is True

            def _mesh():
                comp = J.component("comp1")
                tags = [str(x) for x in comp.mesh().tags()]
                if not tags:
                    comp.mesh().create("mesh1"); tags = ["mesh1"]
                comp.mesh(tags[0]).run()
                st = comp.mesh(tags[0]).stat()
                n = None
                for meth in ("getNumElem", "getNumElements", "numElem"):
                    f = getattr(st, meth, None)
                    if callable(f):
                        n = int(f()); break
                if n is None:
                    raise RuntimeError("读不到单元数")
                return {"tag": tags[0], "n_elem": n}
            rec["mesh"] = step("%s 网格" % tag, _mesh, ev)

            t0 = time.perf_counter()
            try:
                J.study(sname).run()
                rec["solve_ok"], rec["solve_error"] = True, None
            except Exception as exc:  # noqa: BLE001
                rec["solve_ok"], rec["solve_error"] = False, "%s: %s" % (
                    type(exc).__name__, str(exc)[:240])
            rec["solve_seconds"] = round(time.perf_counter() - t0, 1)

            # ---- 工程量：域内 max|p|（**上次的失败是我转型写错**：numpy 不让 1 元素数组直接
            #      float()；这里改成 np.asarray().ravel()。变量名不再猜：模型里只有原始场 `p`，
            #      `spl`/`p_abs` 之类是数据侧后算的，模型里没有。）----
            rec["engineering"] = None
            if rec["solve_ok"]:
                import numpy as np
                for ex in FALLBACK_EXPRS:
                    try:
                        out = model.evaluate(ex, "Pa")
                        arr = np.asarray(out[0] if isinstance(out, (tuple, list)) else out,
                                         dtype=float).ravel()
                        rec["engineering"] = {
                            "expr": ex, "unit": "Pa",
                            "max_abs": float(np.nanmax(np.abs(arr))),
                            "min": float(np.nanmin(arr)), "max": float(np.nanmax(arr)),
                            "n_values": int(arr.size)}
                        break
                    except Exception as exc:  # noqa: BLE001
                        ev["errors"].append("%s evaluate(%r) 失败：%s: %s"
                                            % (tag, ex, type(exc).__name__, str(exc)[:160]))

            # ---- 落盘已求解模型（上次白跑过三次，这次不留空手）----
            try:
                dest = RUN_DIR / ("solved_N1_%g.mph" % n1)
                model.save(str(dest))
                rec["solved_model"] = {"path": str(dest.relative_to(REPO)),
                                       "bytes": dest.stat().st_size if dest.is_file() else None}
            except Exception as exc:  # noqa: BLE001
                ev["errors"].append("%s 保存已求解模型失败：%s: %s"
                                    % (tag, type(exc).__name__, str(exc)[:160]))
                rec["solved_model"] = None
            ev["per_point"][tag] = rec
            print("  - %s geom=%s mesh=%s solve=%s(%.1fs) max|p|=%s"
                  % (tag, rec["geometry_ok"], (rec["mesh"] or {}).get("n_elem"),
                     rec["solve_ok"], rec["solve_seconds"],
                     (rec["engineering"] or {}).get("max_abs")), flush=True)

        pts = list(ev["per_point"].values())
        ev["n_solved"] = sum(1 for p in pts if p.get("solve_ok"))
        ev["n_with_engineering"] = sum(1 for p in pts if p.get("engineering"))
        if ev["n_solved"] == len(pts) and ev["n_with_engineering"] == len(pts):
            ev["verdict"] = "holdout_ready"
            ev["verdict_note"] = ("全部小数 N1 点都解出来了且取到工程量 ⇒ **A 分支留出集就绪**；"
                                  "下一步：拟 v2 并用这些点做独立留出比对。")
        elif ev["n_solved"] == len(pts):
            ev["verdict"] = "solved_no_engineering"
            ev["verdict_note"] = "都解出来了，但工程量没取到（见 errors）⇒ 留出集尚不可用。"
        else:
            ev["verdict"] = "partial"
            ev["verdict_note"] = "部分点没解出来 ⇒ 如实记录，缩小留出集或不支持该区间。"
        ev["ok"] = True
    except Exception as exc:  # noqa: BLE001
        ev["errors"].append("fatal: %s: %s" % (type(exc).__name__, exc))
        ev["traceback"] = traceback.format_exc()

    Path(a.out).write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 70)
    print("多点求解：n1s=%s verdict=%s 解出 %d/%d 取到工程量 %d"
          % (n1s, ev.get("verdict"), ev.get("n_solved") or 0, len(n1s),
             ev.get("n_with_engineering") or 0))
    for e in ev["errors"]:
        print("  [错误]", e[:180])
    print("证据：", a.out)
    print("=" * 70)
    return 0 if ev.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
