"""M1：端口与 Zin2 取证（Codex 指令 §3）。

固定 (0.6,4)、**沿用原网格口径**、只改研究频率列表为 5/20/35 MHz，取复数实部与虚部：
`V_inner`、`V_outer`、`I01`、`I02`、`V_outer-V_inner`，并静态读取 `term1`/`R1`/`pot1` 状态与选择。
**不预设第二端口公式**；输出供推导 `Z = 端口参考电压 / 流入正端电流`。

产物：`work\models\port_audit.csv` / `.json`
用法：python work\\tools\\m1_port_audit.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import socket
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
WORK_MODEL = REPO / "work" / "models" / "b_GE_task3_2new_currentdrive_fmax45_v1.mph"
OUT_DIR = REPO / "work" / "models"
FREQS = ("5", "20", "35")
PORT = 2036

# 表达式表：(标签, 表达式, 归属/说明)
EXPRS = [
    ("V_inner_avg", "intop3(es.V)/intop3(1)", "内电极 cyl9 面平均电位"),
    ("V_outer_avg", "intop4(es.V)/intop4(1)", "外电极 cyl8 面平均电位"),
    ("V_outer_diff_inner", "(intop4(es.V)/intop4(1))-(intop3(es.V)/intop3(1))", "两电极电位差"),
    ("I01", "intop3(es.JZ)", "内电极面电流积分（Zin1 的分子来源）"),
    ("I02", "intop4(es.JZ)", "外电极面电流积分"),
    ("es_term1_V0_ode", "es.term1.V0_ode", "Circuit Terminal 的端口电压 ODE 变量"),
    ("es_term1_Q0_ode", "es.term1.Q0_ode", "Circuit Terminal 的端口电荷 ODE 变量"),
    ("es_V0_1", "es.V0_1", "termI1.V_src 引用的电压变量"),
    ("Zin1", "Zin1", "变量 Zin1（= v0/I01）"),
    ("Zin2", "Zin2", "变量 Zin2（待审计）"),
    ("Ptot", "Ptot", "固定外半球控制面向外声功率（仅作伴随量记录）"),
]


def port_open(p: int = PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", p), timeout=1.5):
            return True
    except OSError:
        return False


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    import numpy as np
    import mph

    staged = None
    if not WORK_MODEL.is_file():
        print(f"[STOP] 工作副本不存在：{WORK_MODEL}")
        return 2
    staged_sha = hashlib.sha256(WORK_MODEL.read_bytes()).hexdigest()
    print(f"工作副本 {WORK_MODEL.name}｜sha256 {staged_sha[:16]}…")

    started = not port_open()
    client = mph.Client(port=PORT) if not started else mph.start(cores=1, port=PORT)
    server_pid = None
    model = client.load(str(WORK_MODEL))
    java = model.java
    comp = java.modelNode("comp1")
    print(f"COMSOL {client.version}｜本脚本启动 server={started}")

    java.param().set("x_scale", "0.6")
    java.param().set("N_w_te1", "4")
    # 关闭参数扫描步，只保留 freq；仅改频率列表，不动网格
    for tag in ("param", "param2"):
        try:
            java.study("std1").feature(tag).active(False)
            print(f"  已停用 study step: {tag}")
        except Exception as exc:
            print(f"  停用 {tag} 失败/不存在：{type(exc).__name__}")
    java.study("std1").feature("freq").set("plist", " ".join(f"{f}[MHz]" for f in FREQS))
    print(f"  频率列表设为：{' '.join(FREQS)} MHz")

    # 静态：驱动与电路拓扑状态
    static = {}
    for label, getter in (
        ("pot1_active", lambda: bool(comp.physics("es").feature("pot1").isActive())),
        ("term1_active", lambda: bool(comp.physics("es").feature("term1").isActive())),
        ("pot2_active", lambda: bool(comp.physics("es").feature("pot2").isActive())),
        ("term1_selection", lambda: sorted(int(v) for v in
                                           comp.physics("es").feature("term1").selection().entities())),
        ("pot2_selection", lambda: sorted(int(v) for v in
                                          comp.physics("es").feature("pot2").selection().entities())),
        ("pot1_selection", lambda: sorted(int(v) for v in
                                          comp.physics("es").feature("pot1").selection().entities())),
        ("R1_resistance", lambda: str(comp.physics("cir").feature("R1").getString("R"))),
        ("termI1_V_src", lambda: str(comp.physics("cir").feature("termI1").getString("V_src"))),
        ("Zin1_expr", lambda: str(comp.variable("var1").getString("Zin1"))),
        ("Zin2_expr", lambda: str(comp.variable("var1").getString("Zin2"))),
        ("I01_expr", lambda: str(comp.variable("var1").getString("I01"))),
        ("I02_expr", lambda: str(comp.variable("var1").getString("I02"))),
    ):
        try:
            static[label] = getter()
        except Exception as exc:
            static[label] = f"<{type(exc).__name__}: {str(exc)[:80]}>"
    print("  静态读取：")
    for k, v in static.items():
        print(f"    {k} = {v}")

    t0 = time.perf_counter()
    java.study("std1").run()
    solve_s = round(time.perf_counter() - t0, 1)
    print(f"  求解完成：{solve_s} s")

    def cx(expr: str, i: int):
        """返回 (re, im, err)。用 real()/imag() 两个求值避免依赖 getComplex。"""
        try:
            re_ = float(np.asarray(model.evaluate(f"real({expr})", inner=[i]),
                                   dtype=float).ravel()[0])
            im_ = float(np.asarray(model.evaluate(f"imag({expr})", inner=[i]),
                                   dtype=float).ravel()[0])
            return re_, im_, None
        except Exception as exc:
            return None, None, f"{type(exc).__name__}: {str(exc)[:90]}"

    rows = []
    for i in range(len(FREQS)):
        try:
            f_hz = float(np.asarray(model.evaluate("freq", inner=[i]), dtype=float).ravel()[0])
        except Exception as exc:
            f_hz = float("nan")
            print(f"  [warn] freq 回读失败 i={i}: {exc}")
        rec = {"index": i, "freq_MHz": f_hz / 1e6}
        for label, expr, desc in EXPRS:
            re_, im_, err = cx(expr, i)
            rec[f"{label}_re"] = re_
            rec[f"{label}_im"] = im_
            rec[f"{label}_abs"] = (abs(complex(re_, im_)) if re_ is not None else None)
            rec[f"{label}_arg_deg"] = (__import__("math").degrees(__import__("math").atan2(im_, re_))
                                       if re_ is not None else None)
            if err and i == 0:
                print(f"    [expr-fail] {label}: {err}")
        rows.append(rec)

    # 汇总判据（供 §3.3 回答）
    summary = {"solve_seconds": solve_s, "static": static, "freqs_MHz": [r["freq_MHz"] for r in rows]}
    try:
        d = [complex(r["V_outer_diff_inner_re"], r["V_outer_diff_inner_im"]) for r in rows]
        summary["Vdiff_abs"] = [abs(x) for x in d]
        summary["Vdiff_phase_deg"] = [__import__("math").degrees(__import__("math").atan2(x.imag, x.real))
                                      for x in d]
        summary["Vdiff_phase_relative_to_5MHz_deg"] = [summary["Vdiff_phase_deg"][k]
                                                       - summary["Vdiff_phase_deg"][0]
                                                       for k in range(len(rows))]
    except Exception as exc:
        summary["Vdiff_error"] = str(exc)

    (OUT_DIR / "port_audit.json").write_text(json.dumps(
        {"work_model": str(WORK_MODEL), "work_model_sha256": staged_sha,
         "comsol_version": str(client.version), "mph_version": mph.__version__,
         "drive_mode": "circuit_terminal_1ohm_current_model",
         "frequencies_MHz": list(FREQS), "summary": summary, "rows": rows},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (OUT_DIR / "port_audit.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    try:
        client.clear()
        client.disconnect()
    except Exception:
        pass
    time.sleep(1)
    print(f"\n端口 {PORT} 仍开放={port_open()}")
    print(f"产物：{OUT_DIR / 'port_audit.csv'}｜{OUT_DIR / 'port_audit.json'}")
    for r in rows:
        print(f"  {r['freq_MHz']:.0f} MHz: V_in={r['V_inner_avg_abs']} ∠{r['V_inner_avg_arg_deg']:.1f}°｜"
              f"V_out={r['V_outer_avg_abs']} ∠{r['V_outer_avg_arg_deg']:.1f}°｜"
              f"I01={r['I01_abs']}｜I02={r['I02_abs']}｜Zin1={r['Zin1_abs']}｜Zin2={r['Zin2_abs']}")
    return 0


if __name__ == "__main__":
    import os as _os

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(code)
