# -*- coding: utf-8 -*-
"""裁定字段完备性门禁：把「用户裁定要求研究/输出的量」逐条对到主表列上，**缺一即报**。

为什么需要它：用户问过「我们前面讨论过要研究哪些计算结果，再检查一下看看需不需要完善」。
这类问题靠人眼扫 60 多列必然漏（实测第一版漏了 3 个通道 + 8 个裁定 §4 字段）。
本脚本把裁定条目**编码成期望清单**，以后每次重建标签表都跑一遍，防止回归。

用法：
    python -B work/tools/check_ruling_fields.py [csv路径]
缺省 csv = work/runs/first-peak-20260929/multichannel_labels.csv
退出码 0 = 无缺口；1 = 有缺口（打印缺口清单）。
"""
from __future__ import annotations

import csv
import math
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"

#: 裁定 §3 判据 → 必须存在的列（**一条判据可以要多个列**）
CRITERIA: dict[str, list[str]] = {
    "§3.1 振幅：中心位移 |w|": ["abs_w_m"],
    "§3.1 振幅：结构速度幅值 |vz|": ["abs_vz_struct_m3s"],
    "§3.1 振幅：声压幅值 |p|": ["abs_p_Pa"],
    "§3.1 振幅：SPL": ["spl_dB", "peak_SPL_dB"],
    "§3.2 带宽：左右 −3 dB 截止": ["f_lo_3dB_Hz", "f_hi_3dB_Hz"],
    "§3.2 带宽：绝对带宽": ["bandwidth_Hz"],
    "§3.2 带宽：Q / ζ（**仅作门禁**）": ["Q_factor", "damping_ratio"],
    "§3.3 灵敏度：单位电压响应（结构速度）": ["abs_vz_struct_per_V_m3s"],
    "§3.3 灵敏度：单位电压响应（位移/声压/SPL）":
        ["abs_w_per_V_m", "abs_p_per_V_Pa", "spl_per_V_dB"],
    "§3.3 驱动口径 ΔV": ["v_inner_V", "v_outer_V", "delta_V_V", "normalization_formula"],
    "§3.4 约束（功率/应力/能量）**只作约束、不排名**":
        ["abs_pv_W", "abs_stress_zz_N", "sGp_du_W", "u_du_m4s2"],
}

#: 裁定 §4 明确要求的 18 个字段
RULING_FIELDS = ["x_scale", "N_w_te1", "N_w_te2", "f_peak_Hz", "peak_SPL_dB",
                 "peak_displacement_m", "f_lo_3dB_Hz", "f_hi_3dB_Hz", "bandwidth_Hz",
                 "Q_factor", "damping_ratio", "peak_closed", "bandwidth_closed",
                 "method", "extrapolated", "ranking_eligible", "source_model",
                 "source_dataset"]


#: 这些字段是**字符串/布尔**，不能用「能否 float」判非空（否则会把
#: `single_dof_fit`/`batch_A` 这类合法值误报成 0% 非空 —— 第一版检查器正是如此）
TEXT_FIELDS = {"method", "source_model", "source_dataset"}
#: 允许有值率低于 100% 的字段：受「带宽闭合/拟合成功」限制（未闭合就没有截止频率）
ALLOW_NULL = {"f_lo_3dB_Hz", "f_hi_3dB_Hz", "bandwidth_Hz", "Q_factor", "damping_ratio",
              "peak_displacement_m", "method", "extrapolated", "ranking_eligible",
              "peak_closed", "bandwidth_closed"}


def is_filled(v, field: str = "") -> bool:
    """字段是否「有值」：文本字段看非空，其余看能否解析为有限数/布尔。"""
    if v is None or v == "":
        return False
    if field in TEXT_FIELDS:
        return bool(str(v).strip())
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return str(v).strip().lower() in ("true", "false")


def main(argv: list[str]) -> int:
    path = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_CSV
    if not path.exists():
        print("[缺] 找不到 %s" % path)
        return 1
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    cols = set(rows[0].keys()) if rows else set()
    print("表：%s" % path.name)
    print("行数：%d ｜ 列数：%d" % (len(rows), len(cols)))

    gaps: list[str] = []
    print("\n── 裁定 §3 判据覆盖 ──")
    for name, need in CRITERIA.items():
        miss = [c for c in need if c not in cols]
        if miss:
            gaps.append("§3 判据缺失列：%s → %s" % (name, miss))
            print("  [缺] %-42s 缺列 %s" % (name, miss))
        else:
            print("  [OK] %-42s %s" % (name, need))

    print("\n── 裁定 §4 必需字段（18 项）──")
    miss4 = [c for c in RULING_FIELDS if c not in cols]
    if miss4:
        gaps.append("§4 必需字段缺失：%s" % miss4)
        print("  [缺] %s" % miss4)
    else:
        # 列在还不够：对「有首峰」的行要求**非空**（否则是"列齐全但值全空"的假完备）
        peaked = [r for r in rows if str(r.get("first_peak_found", "")).lower() == "true"]
        print("  列齐全 ✓ ｜ 有首峰行 %d" % len(peaked))
        for c in RULING_FIELDS:
            n_ok = sum(1 for r in peaked if is_filled(r.get(c), c))
            rate = n_ok / len(peaked) if peaked else 0.0
            flag = "OK" if (rate >= 0.99 or c in ALLOW_NULL) else "缺"
            if flag == "缺":
                gaps.append("§4 字段 %s 在首峰行上非空率仅 %.1f%%" % (c, 100 * rate))
            print("     %-24s 非空 %5.1f%%  [%s]" % (c, 100 * rate, flag))

    print("\n── 其他 建议列 ──")
    for c in ("x_density_class", "freq_grid_MHz", "n_freq", "q_gate_applicable",
              "q_gate_range", "q_gate_pass", "quarantined"):
        print("  %s %s" % ("[OK]" if c in cols else "[缺]", c))
        if c not in cols:
            gaps.append("建议列缺失：%s" % c)

    print("\n══ 结论 ══")
    if gaps:
        print("**存在 %d 项缺口**：" % len(gaps))
        for g in gaps:
            print("  - %s" % g)
        return 1
    print("**0 缺口**：裁定 §3 判据与 §4 必需字段在主表中全部齐备。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
