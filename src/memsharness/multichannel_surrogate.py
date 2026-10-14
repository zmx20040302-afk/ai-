# -*- coding: utf-8 -*-
"""多通道一阶峰代理的**运行时**（供网页/MCP 查询）。

与响应级代理（`surrogate.py`）同一套纪律：
* 加载时**双重校验**（自校验 `model_id` + 标签表哈希）——文件被改过就拒绝启动；
* 越界/无可用预测时**不返回任何数字**，只说明原因（fail-closed）；
* **不是求解器**：只给一阶峰标量，且必须同时给出**适用域、覆盖率口径与区间半宽**；
* α 只认校准过的档位（`ALLOWED_ALPHAS`），其它取值一律拒答。

产物：`work/runs/multichannel-surrogate-20260929/multichannel_model.json`
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
from functools import lru_cache

REPO = pathlib.Path(__file__).resolve().parents[2]
MODEL_PATH = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"
LABELS_PATH = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"

#: 只认这些 α（其它取值没有校准记录 ⇒ 拒答）；与响应级代理保持一致
ALLOWED_ALPHAS = (0.10, 0.05, 0.01)

#: 正式目标（裁定）：带宽 / 位移幅值 / 声压灵敏度
FORMAL_OBJECTIVES = ("bandwidth_Hz", "abs_w_m", "abs_p_per_V_Pa")
#: §3.4 约束量：**只作约束，永不进预测目标**（本模块明确不认）
CONSTRAINT_ONLY = ("abs_pv_W", "abs_stress_zz_N", "sGp_du_W", "u_du_m4s2")

#: 隔离组合的拒答代号（供筛查直方图归类；**这个串被用例锁住，不得改写**）
QUARANTINE_CODE = "quarantined_pending_rerun"


class Refused(Exception):
    """拒答：带可读原因；**调用方不得把它当成错误**，而是「设计如此」。"""


def quarantined(m: dict, x: float, n1: float, n2: float) -> bool:
    """该组合是否落在模型的**隔离名单**（`excluded_quarantine`）里。

    语义：隔离 = 这些角点在跨批比对中异常、**已从拟合中剔除**，但其自身标签仍不可信
    （待重跑）。**剔除只影响拟合，不自动影响查询** ⇒ 若不在此处拒答，
    查询会拿"没有该点"的邻层插值**给出一个看似正常的数字**，把未决数据伪装成已决结论。
    这就是门禁 #10 指出的「`predict()` 不读 `excluded_quarantine`」。
    """
    for q in (m.get("excluded_quarantine") or []):
        try:
            qx, qn1, qn2 = float(q[0]), float(q[1]), float(q[2])
        except (TypeError, ValueError, IndexError):
            continue
        if (abs(float(x) - qx) <= 1e-6 and abs(float(n1) - qn1) <= 1e-9
                and abs(float(n2) - qn2) <= 1e-9):
            return True
    return False


@lru_cache(maxsize=2)
def load(path: str | None = None) -> dict:
    """加载并**校验**模型。校验不过一律抛异常（宁可起不来，不可给错数）。"""
    p = pathlib.Path(path) if path else MODEL_PATH
    if not p.is_file():
        raise FileNotFoundError(
            "缺多通道模型：%s（先跑 export_multichannel_model.py）" % p)
    model = json.loads(p.read_text(encoding="utf-8"))
    # ① 自校验：model_id 必须是"除 model_id 之外全部内容"的哈希
    claimed = model.get("model_id")
    body = {k: v for k, v in model.items() if k != "model_id"}
    got = hashlib.sha256(json.dumps(body, ensure_ascii=False,
                                    sort_keys=True).encode("utf-8")).hexdigest()
    if claimed != got:
        raise ValueError("模型自校验失败：model_id 与内容不符（文件被改动过？）")
    # ② 数据血缘：标签表哈希必须一致（否则模型与数据版本不匹配）
    lp = REPO / model.get("labels_path", "")
    if lp.is_file():
        now = hashlib.sha256(lp.read_bytes()).hexdigest()
        if now != model.get("labels_sha256"):
            raise ValueError("标签表哈希与模型记录不符：模型是旧数据版本拟合的")
    return model


def model_card(path: str | None = None) -> dict:
    """模型卡：**身份/血缘/结构/适用域/逐通道细节/评估/短板**一次说清。

    设计原则：卡片要能独立回答「这个数能不能用」——所以必须给
    ① 数据与预注册的**哈希血缘**、② 每个通道**三个 α 的半宽**、
    ③ 每层在哪些 x 上标定过、④ 主判定折的**逐通道数字与覆盖率**、
    ⑤ 拒答原因构成、⑥ 明确列出**未优于基线**的通道。
    """
    m = load(path)
    ev = m.get("evaluation") or {}
    per_ch = ev.get("per_channel") or {}
    conf = m.get("conformal") or {}
    ch = []
    for name, c in m["channels"].items():
        e = per_ch.get(name) or {}
        ch.append({
            "channel": name, "group": c["group"],
            "is_formal_objective": c["is_formal_objective"],
            "space": c["space"], "requires": c["requires"],
            "n_layers": c["n_layers"], "n_rows_defined": c["n_rows_defined"],
            "coverage_by_n2": c.get("coverage_by_n2") or {},
            # 三个 α 的保形半宽（按模式分开：层内插值 vs N2 外推，难度不同）
            "half_width_by_mode": {
                mode: {a: (conf.get(mode) or {}).get(name, {}).get(a)
                       for a in ("0.1", "0.05", "0.01")}
                for mode in ("in_layer", "n2_extrap")},
            "half_width_alpha_0_05": _half_width(m, name, 0.05),
            "evaluation": {
                "verdict": e.get("verdict_n2_extrap"),
                "median": e.get("median"), "p90": e.get("p90"), "max": e.get("max"),
                "n_predicted": e.get("n_predicted"), "coverage": e.get("coverage"),
                "without_lift": bool(e.get("beats_persistence") is False
                                     and e.get("median") is not None),
                "lift_vs_persistence": e.get("lift_vs_persistence"),
                "baseline_persistence_median": e.get("baseline_persistence_median"),
                "hotspot": e.get("hotspot"),
                "refusal_reasons": e.get("refusal_reasons") or {},
            },
            "eval_verdict": _eval_verdict(m, name),
        })
    return {
        "model_id": m["model_id"], "version": m["version"], "status": m["status"],
        "created": m.get("created"),
        "not_a_solver": m["NOT_a_solver"],
        "structure": m["structure"], "refusal_domain": m["refusal_domain"],
        "formal_objectives": list(FORMAL_OBJECTIVES),
        "constraint_only_not_predictable": list(CONSTRAINT_ONLY),
        "data": {
            "labels_path": m.get("labels_path"), "labels_sha256": m.get("labels_sha256"),
            "batch": m.get("batch"), "n_rows_fit": m.get("n_rows_fit"),
            "n_rows_used_in_eval": ev.get("n_rows_used"),
            "excluded_quarantine": m.get("excluded_quarantine"),
            "n2_layers_fitted": sorted({float(k.split("|")[0])
                                        for k in m["channels"]["abs_w_m"]["layers"]}),
        },
        "lineage": {
            "prereg": m.get("prereg_sha256"),
            "eval_report": ev.get("report"),
            "main_fold": ev.get("main_fold"),
            "model_json": "work/runs/multichannel-surrogate-20260929/multichannel_model.json",
            "exporter": "work/runs/multichannel-surrogate-20260929/export_multichannel_model.py",
        },
        "bands_preregistered": ev.get("bands"),
        "channels": ch,
        "evaluation_summary": {
            "verdict": ev.get("verdict"),
            "channels_without_lift": ev.get("channels_without_lift") or [],
            "note": ev.get("note"),
        },
        "coverage_rule": ("每个预测都必须同时报：**是否命中适用域**、该通道的**区间半宽**、"
                          "以及评估折里的**覆盖率**（覆盖率<1 表示有一部分组合无法预测）"),
        "coverage_semantics": ("⚠️ 评估折覆盖率（约 70%）是**把全新层 N2=8 从 N2∈{5,6,7} 外推**的"
                               "可预测比例，属**最保守**口径；部署模型已含 N2=8 层，"
                               "层内查询的可答率显著更高，只有外推到 N2=9 或相邻层缺同一 x 标定值时才拒答。"
                               "两者**不可互相替代**。"),
    }


def _eval_verdict(m: dict, ch: str) -> dict:
    ev = (m.get("evaluation") or {})
    return {"verdict": ev.get("verdict"),
            "without_lift": ch in (ev.get("channels_without_lift") or []),
            "report": ev.get("report")}


def _half_width(m: dict, ch: str, alpha: float) -> float | None:
    conf = (m.get("conformal") or {})
    for mode in ("in_layer", "n2_extrap"):
        v = (conf.get(mode) or {}).get(ch)
        if isinstance(v, dict):
            h = v.get("%g" % alpha)
            if h is not None:
                return h
    return None


def _layer(m: dict, ch: str, n2: float, n1: float):
    return m["channels"][ch]["layers"].get("%g|%g" % (n2, n1))


def parse_params(x, n1, n2) -> tuple[float, float, float]:
    try:
        return float(x), float(n1), float(n2)
    except (TypeError, ValueError):
        raise Refused("参数必须是数字：x=%r N_w_te1=%r N_w_te2=%r" % (x, n1, n2))


def check_domain(x: float, n1: float, n2: float) -> None:
    """适用域判定；不通过就抛 `Refused`（**不带任何数字**）。"""
    lo, hi = 0.20, 1.00
    if not (lo <= x <= hi):
        raise Refused("x_scale 必须在 [%.2f, %.2f]（批 C 的标定范围）" % (lo, hi))
    if abs(n1 - round(n1)) > 1e-9 or n1 < 1:
        raise Refused("N_w_te1 必须是 ≥1 的整数（收到 %r）" % n1)
    if not (5 <= n2 <= 9):
        raise Refused("N_w_te2 必须在 [5, 9]（9 为 1 步外推上限）")
    if round(n1) >= n2:
        raise Refused("该层不存在：要求 N_w_te1 < N_w_te2（收到 N1=%g, N2=%g）" % (n1, n2))


def _interp(xs: list[float], zs: list[float], x: float) -> float | None:
    """单调 PCHIP（形状保持）；**超出节点范围返回 None ⇒ 拒答**，绝不外推。"""
    if len(xs) < 2 or x < xs[0] or x > xs[-1]:
        return None
    # 线性查找足够：每层 ≤81 个节点
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            x0, x1 = xs[i], xs[i + 1]
            y0, y1 = zs[i], zs[i + 1]
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            # 用三次 Hermite（Fritsch–Carlson 斜率）保证形状保持
            m0 = _slope(xs, zs, i)
            m1 = _slope(xs, zs, i + 1)
            h = x1 - x0
            h00 = 2 * t ** 3 - 3 * t ** 2 + 1
            h10 = t ** 3 - 2 * t ** 2 + t
            h01 = -2 * t ** 3 + 3 * t ** 2
            h11 = t ** 3 - t ** 2
            return h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1
    return None


def _slope(xs, zs, i) -> float:
    """PCHIP 端点/内部斜率（Fritsch–Carlson 加权调和平均）。"""
    n = len(xs)
    if n == 2:
        return (zs[1] - zs[0]) / (xs[1] - xs[0])
    if i == 0:
        return (zs[1] - zs[0]) / (xs[1] - xs[0])
    if i == n - 1:
        return (zs[n - 1] - zs[n - 2]) / (xs[n - 1] - xs[n - 2])
    h0, h1 = xs[i] - xs[i - 1], xs[i + 1] - xs[i]
    d0, d1 = (zs[i] - zs[i - 1]) / h0, (zs[i + 1] - zs[i]) / h1
    if d0 * d1 <= 0:
        return 0.0
    w0, w1 = 2 * h1 + h0, h1 + 2 * h0
    return (w0 + w1) / (w0 / d0 + w1 / d1)


def predict(x, n1, n2, *, channels=None, alpha: float = 0.05,
            path: str | None = None) -> dict:
    """预测若干通道。返回 dict；**任何通道无法给数就整体拒答**（不混半套数字）。"""
    m = load(path)
    x, n1, n2 = parse_params(x, n1, n2)
    if alpha not in ALLOWED_ALPHAS:
        raise Refused("α 只认 %s（其它取值没有校准记录）" % (list(ALLOWED_ALPHAS),))
    names = list(channels or FORMAL_OBJECTIVES)
    # ⚠️ 约束量的检查必须**排在"未知通道"之前**：否则 `abs_pv_W` 会先被当成"未知通道"报错，
    #    掩盖真正的原因（它是 §3.4 的约束量，按裁定**永不进预测目标**）。
    bad = [c for c in names if c in CONSTRAINT_ONLY]
    if bad:
        raise Refused("%s 是 §3.4 的约束量（功率/应力/能量），**只作约束、不进预测目标**" % bad)
    unknown = [c for c in names if c not in m["channels"]]
    if unknown:
        raise Refused("未知通道 %s；可用：%s" % (unknown, sorted(m["channels"])))
    check_domain(x, n1, n2)
    # 隔离名单**排在适用域之后、出数之前**：域内但被隔离的组合同样必须拒答（门禁 #10）
    if quarantined(m, x, n1, n2):
        raise Refused("%s：组合 (x=%g, N1=%g, N2=%g) 在跨批比对中异常、"
                      "**已从拟合中剔除但标签仍待重跑** ⇒ 拒答（不给任何数字）。"
                      "隔离名单见模型 `excluded_quarantine`；不得拿邻层插值代替。"
                      % (QUARANTINE_CODE, x, n1, n2))

    out, mode, reasons = {}, None, {}
    for c in names:
        info = m["channels"][c]
        space = info["space"]
        lay = _layer(m, c, n2, n1)
        if lay is not None:
            z = _interp(lay["x"], lay["z"], round(x, 6))
            if z is None:
                reasons[c] = "x 超出该层标定的 x 范围（不外推）"
                continue
            mode = mode or "in_layer"
        else:
            # N2 方向线性外推（只允许 1 步）
            av = sorted({float(k.split("|")[0]) for k in info["layers"]
                         if float(k.split("|")[1]) == n1})
            if not av:
                reasons[c] = "训练层里没有该 N1 ⇒ 无法预测"
                continue
            near = min(av, key=lambda v: abs(v - n2))
            if abs(near - n2) > 1:
                reasons[c] = "N2 外推超过 1 步 ⇒ 拒答"
                continue
            others = [v for v in av if v != near]
            if not others:
                reasons[c] = "该 N1 在训练层里只有一层，单点无法线性外推"
                continue
            other = min(others, key=lambda v: abs(v - near))
            la = _layer(m, c, near, n1)
            lb = _layer(m, c, other, n1)
            xr = round(x, 6)
            try:
                ia, ib = la["x"].index(xr), lb["x"].index(xr)
            except (AttributeError, ValueError):
                reasons[c] = "外推所需的两层在同一个 x 上没有标定值"
                continue
            za, zb = la["z"][ia], lb["z"][ib]
            z = za + (za - zb) / (near - other) * (n2 - near)
            mode = mode or "n2_extrap"
        val = 10 ** z if space == "log10" else z
        hw = _half_width(m, c, alpha)
        out[c] = {
            "value": val,
            "space": space,
            "half_width": hw,
            "interval": ([max(0.0, 10 ** (z - hw)), 10 ** (z + hw)] if (hw is not None
                          and space == "log10") else
                         ([val - hw, val + hw] if hw is not None else None)),
            "group": info["group"], "is_formal_objective": info["is_formal_objective"],
            "eval_verdict": _eval_verdict(m, c),
        }
    if not out:
        raise Refused("该组合在所有请求通道上都无法预测：" + json.dumps(reasons, ensure_ascii=False))
    if reasons:
        # **不混半套数字**：有通道给不出就整体拒答，避免"部分成功"被当成完整结论
        raise Refused("部分通道无法预测，已整体拒答（不给半套数字）："
                      + json.dumps(reasons, ensure_ascii=False))

    return {
        "model_id": m["model_id"], "status": m["status"], "mode": mode,
        "alpha": alpha, "channels": out,
        "query": {"x_scale": x, "N_w_te1": n1, "N_w_te2": n2},
        "caveats": [
            "本模型只预测**一阶峰标量**，不是 AI 求解器：无场级误差界、无 L1 网格收敛。",
            "跨批提醒：只在批 C 的 x 密度与频段上标定，不得声称对批 A 的参数密度成立。",
            "**未优于持续性基线的通道**（工程上直接用相邻层即可）：%s"
            % (", ".join(m.get("evaluation", {}).get("channels_without_lift") or []) or "无"),
            ("覆盖率口径**别混**：评估折 `L-N2ex(8)` 的覆盖率约 70%——那是"
             "**把一个全新层（N2=8）从 N2∈{5,6,7} 外推**时的可预测比例（最保守）；"
             "本部署模型已含 N2=8 层，故**层内查询**（N2∈{5,6,7,8} 且该层标定过该 x）"
             "基本都可答，只有**外推到 N2=9** 或该 (N1,x) 在相邻两层缺标定时才会拒答。"),
        ],
    }


def _classify_refusal(msg: str) -> str:
    """把拒答原因归类，便于筛查时做直方图（**只归类，不改变拒答本身**）。

    ⚠️ **本表的次序就是优先级（先命中先返回），不得随意调换**：
    结构约束的原文是 `该层不存在：要求 N_w_te1 < N_w_te2`，**这句本身含子串 `N_w_te2`**
    ⇒ 若把 `N_w_te2` 排在 `该层不存在` 之前，结构约束会被**误报成 N2 越域**
    （§101.5/§102 实测：E3 的 476 点网格上 102 条被误标）。
    本轮修法**只调次序、不动任何模式与阈值**，故只有「层不存在」这一类的归属会变。
    """
    for key, pat in (("quarantined_pending_rerun", QUARANTINE_CODE),
                     ("no_layer_for_n1", "没有该 N1"), ("need_two_layers", "只有一层"),
                     ("x_outside_layer_range", "超出该层标定"), ("x_out_of_domain", "x_scale"),
                     # ↓ 结构约束必须**先于** N2 越域匹配（上句含 "N_w_te2" 子串，会子串碰撞）
                     ("layer_does_not_exist", "该层不存在"), ("n2_out_of_domain", "N_w_te2"),
                     ("n2_extrap_too_far", "外推超过"), ("x_missing", "同一个 x"),
                     # ↑ 末位追加：**不得插到前面**（前面各条已按 §105 定序，插队会改变既有归属）
                     ("constraint_only_channel", "约束量")):
        if pat in msg:
            return key
    return "other"


def screen(x_min: float = 0.20, x_max: float = 1.00, x_step: float = 0.05,
           n1_min: int = 1, n1_max: int = 7, n2_min: int = 5, n2_max: int = 8,
           *, channels=None, alpha: float = 0.05, top: int = 5,
           path: str | None = None) -> dict:
    """**网格筛查**：在参数网格上跑多通道预测，逐目标给前 N 名 + 拒答统计。

    设计纪律（与 A5 一致）：
    * **按单个目标排名，绝不合成加权总分**——`per_objective` 各说各的；
    * 被拒答的网格点**单独计数并给原因直方图**，不混进排名（否则"排出来的最优"
      可能只是"碰巧没被拒答的那些"，是典型的选择偏倚）；
    * 每格都可能是 `in_layer` 或 `n2_extrap`，**分别计数**（外推的不确定度更大）。
    """
    m = load(path)
    if alpha not in ALLOWED_ALPHAS:
        raise Refused("α 只认 %s" % (list(ALLOWED_ALPHAS),))
    if x_step <= 0:
        raise Refused("x_step 必须为正")
    if x_min > x_max or n1_min > n1_max or n2_min > n2_max:
        raise Refused("区间上下界写反了（min > max）")
    names = list(channels or FORMAL_OBJECTIVES)
    for c in names:
        if c in CONSTRAINT_ONLY:
            raise Refused("%s 是 §3.4 约束量，只作约束、不进预测目标" % c)
        if c not in m["channels"]:
            raise Refused("未知通道 %s" % c)
    # ⚠️ **请求的网格必须与适用域有交集**，否则直接拒答：
    #    实测（有用例抓到）一个完全落在域外的网格会"跑完并返回 0 个可预测点"，
    #    用户看到 n_predicted=0 会以为模型坏了，而不是以为参数写错了。
    dom_x, dom_n2 = m["refusal_domain"]["x"], m["refusal_domain"]["n2"]
    if x_max < dom_x[0] or x_min > dom_x[1]:
        raise Refused("请求的 x 区间 [%g, %g] 与适用域 [%g, %g] 没有交集"
                      % (x_min, x_max, dom_x[0], dom_x[1]))
    if n2_max < dom_n2[0] or n2_min > dom_n2[1]:
        raise Refused("请求的 N2 区间 [%d, %d] 与适用域 [%d, %d] 没有交集"
                      % (n2_min, n2_max, dom_n2[0], dom_n2[1]))
    if n1_min < 1:
        raise Refused("N_w_te1 必须 ≥ 1")

    ok, reasons, modes = [], {}, {}
    nx = max(1, int(round((x_max - x_min) / x_step)) + 1)
    for i in range(nx):
        x = round(min(x_max, x_min + i * x_step), 6)
        for n1 in range(int(n1_min), int(n1_max) + 1):
            for n2 in range(int(n2_min), int(n2_max) + 1):
                try:
                    r = predict(x, n1, n2, channels=names, alpha=alpha, path=path)
                except Refused as exc:
                    k = _classify_refusal(str(exc))
                    reasons[k] = reasons.get(k, 0) + 1
                    continue
                modes[r["mode"]] = modes.get(r["mode"], 0) + 1
                ok.append({"x_scale": x, "N_w_te1": n1, "N_w_te2": n2, "mode": r["mode"],
                           "values": {c: r["channels"][c]["value"] for c in names}})

    per_obj = {}
    for c in names:
        vals = [p for p in ok if p["values"].get(c) is not None]
        if not vals:
            per_obj[c] = {"n": 0, "top": [], "note": "该网格上没有可预测点"}
            continue
        # 方向：本代理的可排名通道都是"越大越好"（振幅/带宽/灵敏度）；Q 只作门槛、从不作目标。
        srt = sorted(vals, key=lambda p: -p["values"][c])
        per_obj[c] = {
            "n": len(vals), "best": srt[0]["values"][c], "group": m["channels"][c]["group"],
            "top": [{"x_scale": p["x_scale"], "N_w_te1": p["N_w_te1"], "N_w_te2": p["N_w_te2"],
                     "value": p["values"][c], "mode": p["mode"]} for p in srt[:max(1, top)]],
        }
    n_grid = nx * (int(n1_max) - int(n1_min) + 1) * (int(n2_max) - int(n2_min) + 1)
    if not ok:
        # 整个网格都不可预测 ⇒ 拒答（**不要返回一份空排名**让人误以为结果有效）
        raise Refused("该网格内没有任何可预测点，已整体拒答。拒答原因计数：%s"
                      % json.dumps(reasons, ensure_ascii=False))
    return {
        "model_id": m["model_id"], "status": m["status"], "alpha": alpha,
        "grid": {"x": [x_min, x_max, x_step], "n1": [n1_min, n1_max], "n2": [n2_min, n2_max],
                 "n_points": n_grid},
        "n_predicted": len(ok), "n_refused": n_grid - len(ok),
        "coverage": len(ok) / n_grid if n_grid else None,
        "refusal_reasons": reasons, "modes": modes, "per_objective": per_obj,
        "no_weighted_total": ("**不含加权总分**：每个目标各自排序（A5 规则）；"
                              "Q/ζ 只作门槛，从不参与排名。"),
        "caveats": ["结果只覆盖**可预测点**；被拒答的点已单独计数（见 refusal_reasons），"
                    "不得把「排名第一」当成「全局最优」——未覆盖区域可能是更好的设计。",
                    "`n2_extrap` 的点不确定度大于 `in_layer`（见模型卡的分模式半宽）。",
                    "本代理不是 AI 求解器：无场级误差界、无 L1 ⇒ 只用于趋势与选点。"],
    }
