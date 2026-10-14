# -*- coding: utf-8 -*-
"""清点导出物里**到底有哪些结果维度**（列级证据，不凭印象）。

为什么需要它：响应级代理目前只建模了 **SPL 一条频谱**（+ SPL20 + |p|20）。
用户指出"我的计算结果是多维度考虑的" ⇒ 必须先把可用的物理量**逐列清点出来**，
再决定把哪些纳入代理的目标向量（每多一维都要重新做保形校准）。

对每个 `*.txt`：
* 打印列名（`%` 头行，**逐列**而不是按空格切——英文表头里有单空格分隔的列名）；
* 打印该列在前若干行的取值范围/是否有复数字符串；
* 对每个文件汇总"可作为通道的列"。

用法：python -B work/tools/inventory_result_channels.py [镜像目录 ...]
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_MIRRORS = [REPO / "work/runs/n2-8-intake-20260929/raw",
                   REPO / "work/runs/x-densify-20260928/mirror"]

#: 参数列（不是结果通道）：导出表逐行回显的设计参数
PARAM_COLS = ("x_scale", "N_w_te1", "N_w_te2", "freq (Hz)")

#: ⚠️ **列名映射必须写死并附原文**：COMSOL 的表头行用**空白**分隔列名，
#: 但长列名内部本身含空格、且有些边界只有 1 个空格 ⇒ 按空格切**一定会切错**
#: （本工具第一版就是这么错的，把 `Total acoustic pressure (Pa)` 切成了 4 段）。
#: 下表的索引与名称是**逐列人工核对过**的（0–3 恒为参数 + freq）。
CHANNELS = {
    "Table_9.txt": {
        "raw": ("x_scale | N_w_te1 | N_w_te2 | freq (Hz) | real(acpr.v_tz) (m/s), Point: (0,0,-1E-5) | "
                "imag(acpr.v_tz) | Total acoustic velocity, z-component (m/s) | real(acpr.p_t) (Pa) | "
                "imag(acpr.p_t) (Pa) | Total acoustic pressure (Pa) | Total acoustic pressure, RMS (Pa) | "
                "N_w_te1 | N_w_te2 | x_scale | Total sound pressure level (dB)"),
        "cols": {4: "real(acpr.v_tz) [m/s] @声域点(0,0,-1e-5)", 5: "imag(acpr.v_tz) [m/s]",
                 6: "复声速 v_tz（复数）", 7: "real(acpr.p_t) [Pa]", 8: "imag(acpr.p_t) [Pa]",
                 9: "复声压 p_t（复数）", 10: "p_RMS [Pa]", 11: "(参数回显 N1)", 12: "(参数回显 N2)",
                 13: "(参数回显 x_scale)", 14: "**声压级 SPL [dB re 20µPa]**（现在唯一在用的通道）"}},
    "Table_10.txt": {
        "raw": ("x_scale | N_w_te1 | N_w_te2 | freq (Hz) | Total acoustic pressure (N) | "
                "Total acoustic velocity, z-component (m^3/s) | acpr.v_tz*conj(acpr.v_tz) (m^4/s^2) | "
                "acpr.p_t*conj(acpr.v_tz) (W)"),
        "cols": {4: "总声压（积分，N）复数", 5: "总体积速度 z（积分，m^3/s）复数",
                 6: "v·conj(v)（m^4/s^2）", 7: "**声功率 p·conj(v)（W）复数**"}},
    "Table_11.txt": {
        "raw": ("x_scale | N_w_te1 | N_w_te2 | freq (Hz) | Velocity, Z-component (m^3/s) | "
                "Stress tensor, zz-component (N) | solid.sGpzz*conj(solid.u_tZ) (N*m/s) | "
                "solid.u_tZ*conj(solid.u_tZ) (m^4/s^2) | 1 (m^2) | Displacement field, Z-component (m^3)"),
        "cols": {4: "结构体积速度 z（m^3/s）复数", 5: "**应力张量 zz（N）复数**",
                 6: "**结构功率 sGpzz·conj(u_tZ)（N·m/s）复数**", 7: "u_tZ·conj(u_tZ)（m^4/s^2）",
                 8: "1 (m^2)（常数，无信息）", 9: "结构位移场 z（m^3）"}},
    "Zdisplacement.txt": {
        "raw": ("x_scale | N_w_te1 | N_w_te2 | freq (Hz) | Displacement field, Z-component (m), "
                "Point: (0,0,1E-8) | N_w_te1 | N_w_te2 | x_scale | Velocity, Z-component (m/s) | "
                "real(w) (m) | imag(w) (m)"),
        "cols": {4: "**位移 w（复数，m）@结构点(0,0,1e-8)**", 5: "(参数回显 N1)",
                 6: "(参数回显 N2)", 7: "(参数回显 x_scale)", 8: "结构点速度 z（m/s）复数",
                 9: "real(w) [m]", 10: "imag(w) [m]"}},
    "Peak_frequency.txt": {
        "raw": "freq (Hz) | Total sound pressure level (dB)　← 每个组合取**最大**值（图标记）",
        "cols": {0: "**峰值频率 [Hz]**（每组合一个）", 1: "**峰值处的 SPL [dB]**（每组合一个）"}},
    "Bandwidth.txt": {
        "raw": ("freq (Hz) | Total sound pressure level (dB) | Width (Hz) | Q-factor | Damping ratio"
                "　← 每个组合可有多行（每行一个 -3dB 截止点）"),
        "cols": {0: "截止频率 [Hz]", 1: "截止处 SPL [dB]", 2: "**-3dB 带宽 Width [Hz]**",
                 3: "**Q 因子**", 4: "**阻尼比**"}},
}


def split_header(hdr: str) -> list[str]:
    """列名行按**变长空白**切——英文表头里有的列名只用 1 个空格分隔。"""
    return [s.strip() for s in re.split(r"\s{1,}", hdr.strip()) if s.strip()]


def scan(path: pathlib.Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    hdr, rows, meta = "", [], {}
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("%"):
            body = s.lstrip("%").strip()
            head = body.split(":", 1)[0].strip().lower() if ":" in body else ""
            if head in ("model", "version", "date", "table"):
                meta[head] = body.split(":", 1)[1].strip()
            else:
                hdr = body
            continue
        rows.append(s.split())
    ncol = len(rows[0]) if rows else 0
    cols = split_header(hdr)
    return {"file": path.name, "n_rows": len(rows), "n_cols_data": ncol,
            "n_cols_header": len(cols), "header_cols": cols, "rows": rows, "meta": meta}


def describe(col_idx: int, rows: list, limit: int = 400) -> str:
    vals, complexish, nonnum = [], 0, 0
    for r in rows[:limit]:
        if col_idx >= len(r):
            continue
        v = r[col_idx]
        if ("i" in v and not v.lower().startswith("inf")) and ("+" in v[1:] or "-" in v[1:]):
            complexish += 1
            continue
        try:
            vals.append(float(v))
        except ValueError:
            nonnum += 1
    if complexish and not vals:
        return "复数文本（形如 a+bj）"
    if not vals:
        return "非数值（样本 %d）" % nonnum
    lo, hi = min(vals), max(vals)
    return "n=%d  min=%.6g  max=%.6g" % (len(vals), lo, hi)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mirrors = [pathlib.Path(a).resolve() for a in argv] or DEFAULT_MIRRORS
    for m in mirrors:
        if not m.is_dir():
            print("[SKIP] 不存在：%s" % m)
            continue
        runs = sorted(p for p in m.iterdir() if p.is_dir() and p.name.startswith("cell_"))
        if not runs:
            continue
        print("\n" + "=" * 100)
        print("镜像：%s（%d 个 run）" % (m.relative_to(REPO), len(runs)))
        run = runs[-1]                      # 同一镜像内各 run 结构相同，取一个代表
        for f in sorted(run.glob("*.txt")):
            info = scan(f)
            spec = CHANNELS.get(f.name)
            print("\n--- %s / %s  （数据行 %d，数据列 %d）"
                  % (run.name[-24:], f.name, info["n_rows"], info["n_cols_data"]))
            if spec:
                print("    原文表头：%s" % spec["raw"][:150])
                if len(spec["raw"]) > 150:
                    print("              %s" % spec["raw"][150:])
            for i in range(info["n_cols_data"]):
                name = (spec or {}).get("cols", {}).get(i)
                if name is None:
                    name = "（未知列，需人工核对）"
                print("    [%2d] %-56s %s" % (i, name[:56], describe(i, info["rows"])))
    print("\n提示：`(参数回显 …)` 不是结果通道；`1 (m^2)` 常数无信息量，可忽略。")
    print("可提交给代理的**结果维度**（每维都要单独做保形校准）：")
    print("  A. 频响通道（91 点频谱，与 SPL 同形）：|p|、real/imag(p)、|v|、real/imag(v)、p_RMS、")
    print("     积分声压(N)、体积速度(m^3/s)、|v|^2、声功率 p·conj(v)(W)、")
    print("     结构体积速度、应力 zz(N)、结构功率(N*m/s)、|u|^2、位移场(m^3)、")
    print("     结构点位移 w(m)/real/imag、结构点速度")
    print("  B. 每组合标量：峰值频率、峰值 SPL、-3dB 带宽、Q 因子、阻尼比")
    return 0


if __name__ == "__main__":
    sys.exit(main())
