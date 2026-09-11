"""解析/降阶数据工厂（F0/F1）——"用解析解生成更多数据"的落地件。

对应 WORKING_PLAN §4.3。设计原则：

1. **每个解析模型自带基准测试**（继承既有 `ONE_DIMENSIONAL_MODEL_LIBRARY.md` 的做法）：
   基准必须包含**量纲检查、极限检查、标度律检查、已知值检查**，而不是"跑通不报错"。
   没有基准的解析模型不得进入训练集——它可能与仿真系统性偏差而无人发现。
2. 产物统一标注 `source_type="analytic"`、`fidelity="F0"`（降阶 1D 为 F1），
   并且必须能与同一 `design` 空间下的仿真值做**交叉一致性检查**（见 §4.3）。
3. 解析式一律带单位注释，输入输出按 SI 处理。

本版收录 4 个 MEMS/换能器常用的 F0 模型：
- ``thickness_mode_resonance``：压电板厚度模谐振（PMUT/换能器基础关系）
- ``cantilever_resonance``：悬臂梁一阶弯曲谐振（谐振器/MEMS 梁）
- ``heat_slab_1d``：一维稳态导热温升（与 COMSOL 模板 heat_slab_2d 的解析参考**同源**）
- ``thermal_noise_amplitude``：热噪声位移幅度（谐振器噪声底）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

EXTRACTOR_VERSION = "memsharness.analytic@0.1.0"

# 物理常数（COMSOL 一致）
K_BOLTZMANN = 1.380649e-23  # J/K


@dataclass
class AnalyticModel:
    """一个闭式解/降阶模型：参数声明 + 求值 + **自基准**。"""

    name: str
    title: str
    fidelity: str                       # F0 闭式 / F1 降阶
    inputs: dict[str, tuple[str, float, float]]   # 名称 → (单位, 下界, 上界)
    outputs: dict[str, str]             # 名称 → 单位
    evaluate: Callable[[dict[str, float]], dict[str, float]]
    benchmark: Callable[[], list[dict[str, Any]]]
    geometry_family: str
    notes: str = ""

    def input_names(self) -> list[str]:
        return list(self.inputs)

    def validate(self, params: dict[str, float]) -> dict[str, float]:
        """校验参数是否齐全且在声明范围内（越界直接拒绝，不静默外推）。"""
        missing = [k for k in self.inputs if k not in params]
        if missing:
            raise ValueError(f"{self.name} 缺少参数：{missing}")
        clean: dict[str, float] = {}
        for key, (unit, lo, hi) in self.inputs.items():
            value = float(params[key])
            if not (lo <= value <= hi):
                raise ValueError(
                    f"{self.name} 参数 {key}={value} 超出声明范围 [{lo}, {hi}] {unit}"
                    f"（越界不静默外推）"
                )
            clean[key] = value
        return clean


# ---------------------------------------------------------------------------------------
# F0-1 压电板厚度模谐振
# ---------------------------------------------------------------------------------------


def _thickness_mode(params: dict[str, float]) -> dict[str, float]:
    """f = v_D/(2t)，v_D = sqrt(c_D/rho)：厚度模半波谐振。

    这是 PMUT/换能器最基本的频率-厚度关系；c_D 为**夹持（开路）**弹性常数，
    与材料手册里的 c33^D 对应。
    """
    t, c_d, rho = params["t"], params["c_d"], params["rho"]
    v = math.sqrt(c_d / rho)                 # m/s
    f = v / (2.0 * t)                        # Hz
    z = rho * v                              # kg/(m^2*s) 声阻抗
    return {"f_r": f, "v_D": v, "Z_ac": z}


def _thickness_mode_benchmark() -> list[dict[str, Any]]:
    base = {"t": 112e-6, "c_d": 1.5e11, "rho": 7500.0}
    r = _thickness_mode(base)
    checks: list[dict[str, Any]] = []

    # 1) 物理自洽：v = 2·f·t（半波条件）
    checks.append({
        "check": "半波自洽 v = 2 f t",
        "expected": base["c_d"] and math.sqrt(base["c_d"] / base["rho"]),
        "actual": 2.0 * r["f_r"] * base["t"],
        "passed": abs(2.0 * r["f_r"] * base["t"] - r["v_D"]) / r["v_D"] < 1e-12,
    })
    # 2) 标度律：厚度减半 → 频率加倍
    half = _thickness_mode({**base, "t": base["t"] / 2.0})
    checks.append({
        "check": "厚度减半频率加倍",
        "expected": 2.0,
        "actual": half["f_r"] / r["f_r"],
        "passed": abs(half["f_r"] / r["f_r"] - 2.0) < 1e-9,
    })
    # 3) 标度律：刚度 4 倍 → 频率 2 倍
    stiffer = _thickness_mode({**base, "c_d": base["c_d"] * 4.0})
    checks.append({
        "check": "刚度 ×4 频率 ×2",
        "expected": 2.0,
        "actual": stiffer["f_r"] / r["f_r"],
        "passed": abs(stiffer["f_r"] / r["f_r"] - 2.0) < 1e-9,
    })
    # 4) 声阻抗量纲/量级：PZT 约 30–40 MRayl
    checks.append({
        "check": "声阻抗量级（PZT 类 25–45 MRayl）",
        "expected": "25e6–45e6",
        "actual": r["Z_ac"],
        "passed": 25e6 <= r["Z_ac"] <= 45e6,
    })
    return checks


# ---------------------------------------------------------------------------------------
# F0-2 悬臂梁一阶弯曲谐振
# ---------------------------------------------------------------------------------------


def _cantilever(params: dict[str, float]) -> dict[str, float]:
    """f1 = (β₁²/2π)·sqrt(EI/(ρ A L⁴))，β₁ = 1.875104（悬臂一阶）。"""
    E, rho, L, b, h = params["E"], params["rho"], params["L"], params["b"], params["h"]
    I = b * h**3 / 12.0                      # m^4
    A = b * h                                # m^2
    beta1 = 1.875104068711961
    f1 = (beta1**2 / (2.0 * math.pi)) * math.sqrt(E * I / (rho * A * L**4))
    k_spring = E * b * h**3 / (4.0 * L**3)   # N/m 端部刚度
    return {"f_1": f1, "k_spring": k_spring}


def _cantilever_benchmark() -> list[dict[str, Any]]:
    base = {"E": 170e9, "rho": 2330.0, "L": 200e-6, "b": 20e-6, "h": 2e-6}
    r = _cantilever(base)
    checks: list[dict[str, Any]] = []

    # 1) 标度律：长度减半 → 频率 ×4
    shorter = _cantilever({**base, "L": base["L"] / 2.0})
    checks.append({
        "check": "长度减半频率 ×4", "expected": 4.0,
        "actual": shorter["f_1"] / r["f_1"], "passed": abs(shorter["f_1"] / r["f_1"] - 4.0) < 1e-9,
    })
    # 2) 标度律：厚度加倍 → 频率 ×2（I∝h³, A∝h ⇒ sqrt(h²)=h）
    thicker = _cantilever({**base, "h": base["h"] * 2.0})
    checks.append({
        "check": "厚度加倍频率 ×2", "expected": 2.0,
        "actual": thicker["f_1"] / r["f_1"], "passed": abs(thicker["f_1"] / r["f_1"] - 2.0) < 1e-9,
    })
    # 3) 已知值：硅悬臂 200×20×2 µm 一阶频率应落在 10–100 kHz 量级
    checks.append({
        "check": "已知量级（几十 kHz）", "expected": "1e4–1e5",
        "actual": r["f_1"], "passed": 1e4 <= r["f_1"] <= 1e5,
    })
    # 4) 端部刚度与频率的一致性：由 f1 反算刚度，应与解析刚度 3EI/L³ 一致
    #    f1 = (β₁²/2π)·sqrt(EI/(ρAL⁴)) ⇒ EI = (2π f1/β₁²)²·ρAL⁴ ⇒ k = 3EI/L³ = 3·(2π f1/β₁²)²·ρA·L
    beta1 = 1.875104068711961
    A = base["b"] * base["h"]
    k_from_f = 3.0 * (2.0 * math.pi * r["f_1"] / beta1**2) ** 2 * base["rho"] * A * base["L"]
    checks.append({
        "check": "由 f1 反算端部刚度与 3EI/L³ 一致（<1e-9 相对）",
        "expected": r["k_spring"], "actual": k_from_f,
        "passed": abs(k_from_f - r["k_spring"]) / r["k_spring"] < 1e-9,
    })
    return checks


# ---------------------------------------------------------------------------------------
# F0-3 一维稳态导热（与 COMSOL 模板解析参考同源）
# ---------------------------------------------------------------------------------------


def _heat_slab_1d(params: dict[str, float]) -> dict[str, float]:
    """ΔT = q·L/k，T_max = T0 + ΔT（一端定温、另一端入射热流、侧壁绝热）。"""
    q, L, k, T0 = params["q_in"], params["L"], params["k_cond"], params["T0"]
    dT = q * L / k
    return {"T_max": T0 + dT, "T_min": T0, "dT": dT}


def _heat_slab_1d_benchmark() -> list[dict[str, Any]]:
    base = {"q_in": 1000.0, "L": 0.01, "k_cond": 1.0, "T0": 300.0}
    r = _heat_slab_1d(base)
    checks: list[dict[str, Any]] = []

    checks.append({
        "check": "已知值 ΔT = 1000×0.01/1 = 10 K", "expected": 10.0,
        "actual": r["dT"], "passed": abs(r["dT"] - 10.0) < 1e-12,
    })
    # 极限：零热流 → 全场等于 T0
    zero = _heat_slab_1d({**base, "q_in": 0.0})
    checks.append({
        "check": "零热流极限 ΔT=0（全场 T0）", "expected": 0.0,
        "actual": zero["dT"], "passed": abs(zero["dT"]) < 1e-15,
    })
    # 标度：热导率加倍 → 温升减半
    kilo = _heat_slab_1d({**base, "k_cond": 2.0})
    checks.append({
        "check": "热导率加倍温升减半", "expected": 0.5,
        "actual": kilo["dT"] / r["dT"], "passed": abs(kilo["dT"] / r["dT"] - 0.5) < 1e-12,
    })
    # 与 COMSOL 模板的解析参考一致性（同一物理、同一公式族）
    from .comsol.java_model import get_template
    template = get_template("heat_slab_2d")
    ref = template.analytic({"q_in": 1000.0, "Lx": 0.01, "Ly": 0.008, "k_cond": 1.0, "T0": 300.0,
                             "rho_mat": 1000.0, "Cp_mat": 1000.0, "hmax_mesh": 5e-4,
                             "bnd_t": 4.0, "bnd_q": 1.0})
    checks.append({
        "check": "与 COMSOL 模板解析参考一致（T_max）", "expected": ref["T_max_K"],
        "actual": r["T_max"], "passed": abs(r["T_max"] - ref["T_max_K"]) < 1e-9,
    })
    return checks


# ---------------------------------------------------------------------------------------
# F0-4 热噪声位移幅度
# ---------------------------------------------------------------------------------------


def _thermal_noise(params: dict[str, float]) -> dict[str, float]:
    """能量均分：½k⟨x²⟩ = ½k_B T ⇒ x_rms = sqrt(k_B T / k)。"""
    k, T = params["k_spring"], params["T"]
    x_rms = math.sqrt(K_BOLTZMANN * T / k)
    # 位移噪声谱密度（白噪声近似，结构阻尼主导）S_x = 4 k_B T/(k ω0 Q)
    return {"x_rms": x_rms}


def _thermal_noise_benchmark() -> list[dict[str, Any]]:
    base = {"k_spring": 100.0, "T": 300.0}
    r = _thermal_noise(base)
    checks: list[dict[str, Any]] = []

    # 1) 手算核对：k_B T = 4.14e-21 J，/100 N/m = 4.14e-23 m² → sqrt = 6.43e-12 m
    expected = math.sqrt(K_BOLTZMANN * 300.0 / 100.0)
    checks.append({
        "check": "手算核对 x_rms", "expected": expected, "actual": r["x_rms"],
        "passed": abs(r["x_rms"] - expected) < 1e-18,
    })
    # 2) 标度：刚度 ×4 → 幅度减半
    stiffer = _thermal_noise({**base, "k_spring": 400.0})
    checks.append({
        "check": "刚度 ×4 幅度减半", "expected": 0.5,
        "actual": stiffer["x_rms"] / r["x_rms"], "passed": abs(stiffer["x_rms"] / r["x_rms"] - 0.5) < 1e-12,
    })
    # 3) 标度：温度 ×4 → 幅度 ×2
    hotter = _thermal_noise({**base, "T": 1200.0})
    checks.append({
        "check": "温度 ×4 幅度 ×2", "expected": 2.0,
        "actual": hotter["x_rms"] / r["x_rms"], "passed": abs(hotter["x_rms"] / r["x_rms"] - 2.0) < 1e-12,
    })
    # 4) 极限：T → 0 时噪声 → 0
    checks.append({
        "check": "T→0 极限噪声→0", "expected": 0.0,
        "actual": _thermal_noise({"k_spring": 100.0, "T": 0.0})["x_rms"],
        "passed": _thermal_noise({"k_spring": 100.0, "T": 0.0})["x_rms"] < 1e-30,
    })
    return checks


# ---------------------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------------------

MODELS: dict[str, AnalyticModel] = {
    m.name: m for m in (
        AnalyticModel(
            name="thickness_mode_resonance",
            title="压电板厚度模谐振（F0）",
            fidelity="F0",
            inputs={"t": ("m", 1e-7, 1e-3), "c_d": ("Pa", 1e9, 1e12), "rho": ("kg/m^3", 1000.0, 12000.0)},
            outputs={"f_r": "Hz", "v_D": "m/s", "Z_ac": "kg/(m^2*s)"},
            evaluate=_thickness_mode,
            benchmark=_thickness_mode_benchmark,
            geometry_family="GF-plate-thickness-mode",
            notes="f=v_D/(2t)；c_d 为夹持（开路）弹性常数，对应材料手册 c33^D",
        ),
        AnalyticModel(
            name="cantilever_resonance",
            title="悬臂梁一阶弯曲谐振（F0）",
            fidelity="F0",
            inputs={
                "E": ("Pa", 1e9, 1e12), "rho": ("kg/m^3", 1000.0, 25000.0),
                "L": ("m", 1e-6, 1e-2), "b": ("m", 1e-7, 1e-2), "h": ("m", 1e-8, 1e-3),
            },
            outputs={"f_1": "Hz", "k_spring": "N/m"},
            evaluate=_cantilever,
            benchmark=_cantilever_benchmark,
            geometry_family="GF-cantilever-beam",
        ),
        AnalyticModel(
            name="heat_slab_1d",
            title="一维稳态导热温升（F0）",
            fidelity="F0",
            inputs={
                "q_in": ("W/m^2", 0.0, 1e7), "L": ("m", 1e-6, 1.0),
                "k_cond": ("W/(m*K)", 1e-3, 1e5), "T0": ("K", 0.0, 5000.0),
            },
            outputs={"T_max": "K", "T_min": "K", "dT": "K"},
            evaluate=_heat_slab_1d,
            benchmark=_heat_slab_1d_benchmark,
            geometry_family="GF-heat-slab-2d",
            notes="与 COMSOL 模板 heat_slab_2d 的解析参考同源，可直接做交叉一致性检查",
        ),
        AnalyticModel(
            name="thermal_noise_amplitude",
            title="热噪声位移幅度（F0）",
            fidelity="F0",
            inputs={"k_spring": ("N/m", 1e-3, 1e6), "T": ("K", 0.0, 1000.0)},
            outputs={"x_rms": "m"},
            evaluate=_thermal_noise,
            benchmark=_thermal_noise_benchmark,
            geometry_family="GF-resonator-thermal-noise",
        ),
    )
}


def get_model(name: str) -> AnalyticModel:
    if name not in MODELS:
        raise KeyError(f"未知解析模型 {name!r}；已注册：{sorted(MODELS)}")
    return MODELS[name]


def list_models() -> list[dict[str, Any]]:
    return [
        {
            "name": m.name, "title": m.title, "fidelity": m.fidelity,
            "geometry_family": m.geometry_family,
            "inputs": {k: {"unit": u, "min": lo, "max": hi} for k, (u, lo, hi) in m.inputs.items()},
            "outputs": m.outputs, "notes": m.notes,
        }
        for m in MODELS.values()
    ]


def run_benchmarks() -> dict[str, Any]:
    """跑全部解析模型的自基准。**任一失败即整体失败**（没有基准的解析数据不得入训练集）。"""
    report: dict[str, Any] = {"extractor": EXTRACTOR_VERSION, "models": {}}
    all_passed = True
    for m in MODELS.values():
        checks = m.benchmark()
        failed = [c for c in checks if not c.get("passed")]
        all_passed &= not failed
        report["models"][m.name] = {
            "n_checks": len(checks), "n_failed": len(failed),
            "passed": not failed, "checks": checks,
        }
    report["all_passed"] = bool(all_passed)
    report["n_models"] = len(MODELS)
    return report


# ---------------------------------------------------------------------------------------
# 数据生成：按声明范围扫掠解析模型，产出可直接入库的样本行
# ---------------------------------------------------------------------------------------


def generate_designs(
    name: str,
    *,
    n_samples: int = 64,
    overrides: dict[str, float] | None = None,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """在解析模型的声明范围内生成 ``n_samples`` 组设计点（LHS 抽样 + 解析求值）。

    ``overrides`` 用于固定某些参数（例如与仿真对齐时固定 L/k）。
    **越界不生成**：抽样严格在声明范围内进行，且求值前仍走 ``validate``。
    """
    import numpy as np

    model = get_model(name)
    overrides = overrides or {}
    rng = np.random.default_rng(seed)

    free = [k for k in model.inputs if k not in overrides]
    if not free:
        raise ValueError("所有输入参数都被 overrides 固定，无法生成设计点")

    # 拉丁超立方：每个自由参数在其范围内分层抽样，避免网格点聚集
    lhs = np.empty((n_samples, len(free)))
    for j in range(len(free)):
        strata = (np.arange(n_samples) + rng.random(n_samples)) / n_samples
        rng.shuffle(strata)
        lhs[:, j] = strata

    rows: list[dict[str, Any]] = []
    for i in range(n_samples):
        params: dict[str, float] = dict(overrides)
        for j, key in enumerate(free):
            _unit, lo, hi = model.inputs[key]
            params[key] = float(lo + (hi - lo) * lhs[i, j])
        clean = model.validate(params)
        outputs = model.evaluate(clean)
        rows.append({
            "model": model.name,
            "fidelity": model.fidelity,
            "geometry_family": model.geometry_family,
            "inputs": clean,
            "input_units": {k: model.inputs[k][0] for k in clean},
            "outputs": outputs,
            "output_units": dict(model.outputs),
        })
    return rows


def insert_analytic_samples(conn: Any, rows: Sequence[dict[str, Any]], *, design_prefix: str) -> dict[str, Any]:
    """把生成的设计点与解析结果写入元数据库（source_type='analytic'、fidelity 按模型）。

    每个设计点同时写 ``design`` 与 ``sample``：这样解析样本与仿真样本处在**同一参数空间**下，
    后续可直接按 ``design`` 做交叉一致性检查（§4.3）。
    """
    from .store import insert_sample, now_utc
    import json

    inserted = 0
    for i, row in enumerate(rows):
        design_id = f"{design_prefix}-{i:05d}"
        conn.execute(
            "INSERT INTO design (design_id, params, units, geometry_family, source_type, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                design_id,
                json.dumps(row["inputs"], ensure_ascii=False),
                json.dumps(row["input_units"], ensure_ascii=False),
                row["geometry_family"],
                "analytic",
                now_utc(),
            ],
        )
        insert_sample(
            conn,
            sample_id=f"smpl-{design_id}",
            design_id=design_id,
            fidelity=row["fidelity"],
            source_type="analytic",
            inputs=row["inputs"],
            outputs=row["outputs"],
            uncertainty=None,          # 闭式解本身无抽样不确定度；模型形式误差在 quality 里声明
            extractor=EXTRACTOR_VERSION,
            quality={
                "model": row["model"],
                "note": "闭式解：不确定度来自模型形式误差（未量化），不得当作仿真真值使用",
                "l0_benchmark": "见 analytic.run_benchmarks()",
            },
        )
        inserted += 1
    return {"inserted": inserted, "design_prefix": design_prefix}
