# -*- coding: utf-8 -*-
"""响应级代理的**运行时**（加载冻结产物 → 预测 + 认证区间 + 拒答判定）。

它是 `work/runs/surrogate-response-20260929/fit_response_surrogate.py` 的服务端封装，
把那份规格（`SURROGATE_SPEC.md`）变成**可调用的代码事实**：

* **每次预测都必须带**：`model_id` + `data_version` + `alpha` + `certified` + 区间 + 拒答判定 + `not_a_solver` 声明；
* **拒答时不得返回任何数字**（只返回理由）——拒答即回退 COMSOL；
* **状态只能是 `draft_surrogate`**，本模块**没有**任何把状态升级的接口（放行权在人）；
* 加载时**双哈希校验**：文件 sha256（完整性）+ 内容 sha256（身份），任一不符即拒绝加载。

⚠️ 本模块**不会**、也**不得**被用来声称"等价于 COMSOL"：
没有场数据 ⇒ S1 场级误差界不可测；没有 L1 ⇒ 不给工程绝对值。

用法：
    s = ResponseSurrogate.load()                      # 默认读冻结目录
    s.predict(0.55, 1, 6)                             # → dict（含区间与拒答信息）
    s.coverage()                                      # 可答域普查
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO / "work/runs/surrogate-response-20260929"

#: 允许的 α（取自冻结 JSON；其它取值一律拒绝，**不得插值出未校准的区间**）
ALLOWED_ALPHAS = (0.10, 0.05, 0.01)

#: 走 5–50 MHz 的 91 点原生网格；`spec` 的前 91 维
N_SPEC = 91
DIM_SPL20 = 91          # 索引 91 = SPL20(dB)
DIM_P20 = 92            # 索引 92 = |p|20(Pa)
DIM_DB = tuple(range(N_SPEC + 1))     # dB 维度 = 91 频谱点 + SPL20


class SurrogateUnavailable(RuntimeError):
    """产物缺失/哈希不符/规格不合法 ⇒ 拒绝加载（fail-closed）。"""


def _sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ResponseSurrogate:
    """两级结构的响应级代理：层内沿 x 的 PCHIP ＋ 同 (N1,x) 沿 N2 的 1 步线性外推。"""

    model_id: str
    status: str
    data_version: str
    spec_freqs_MHz: np.ndarray
    x_lo: float
    x_hi: float
    n2_fitted: list[float]
    n2_extrap_max: float
    conformal: dict[str, Any]
    quarantine: list[tuple]
    run_dir: pathlib.Path
    artifact_sha256: str
    content_sha256: str
    notice: str
    _layers: dict = field(default_factory=dict, repr=False)
    _by_n1x: dict = field(default_factory=dict, repr=False)

    # ---------------------------------------------------------------- 加载
    @classmethod
    def load(cls, run_dir: pathlib.Path | str | None = None) -> "ResponseSurrogate":
        rd = pathlib.Path(run_dir) if run_dir else DEFAULT_DIR
        jp = rd / "response_surrogate.json"
        if not jp.is_file():
            raise SurrogateUnavailable("缺少 %s" % jp)
        meta = json.loads(jp.read_text(encoding="utf-8"))
        art = meta.get("artifact") or {}
        ap = rd / str(art.get("file") or "")
        if not ap.is_file():
            raise SurrogateUnavailable("缺少产物 %s" % ap)
        got = _sha256_file(ap)
        if got != art.get("file_sha256"):
            raise SurrogateUnavailable(
                "产物文件 sha256 不符（期望 %s，实得 %s）⇒ 拒绝加载"
                % ((art.get("file_sha256") or "")[:16], got[:16]))
        z = np.load(ap)
        if str(z["content_sha256"][0]) != meta.get("content_sha256"):
            raise SurrogateUnavailable("产物内容摘要与 JSON 不符 ⇒ 拒绝加载")
        if meta.get("status") != "draft_surrogate":
            raise SurrogateUnavailable("状态不是 draft_surrogate（%s）⇒ 拒绝加载"
                                       % meta.get("status"))
        # 一致性：产物自身的若干字段
        if int(z["Y"].shape[0]) != int(art.get("n_rows", -1)):
            raise SurrogateUnavailable("产物行数与 JSON 不符")
        if int(z["Y"].shape[1]) != int(art.get("dim", -1)):
            raise SurrogateUnavailable("产物维度与 JSON 不符")

        self = cls(
            model_id=meta["model_id"], status=meta["status"],
            data_version=meta["data_version"],
            spec_freqs_MHz=np.asarray(z["freqs_MHz"], float),
            x_lo=float(meta["predictable_x_range"][0]),
            x_hi=float(meta["predictable_x_range"][1]),
            n2_fitted=[float(v) for v in meta["n2_fitted"]],
            n2_extrap_max=float(meta["n2_extrap_allowed_max"]),
            conformal=meta["conformal"], quarantine=[tuple(q) for q in meta["quarantined_combos"]],
            run_dir=rd, artifact_sha256=got, content_sha256=meta["content_sha256"],
            notice=meta["NOT_a_solver"],
        )
        self._build_layers(z)
        return self

    def _build_layers(self, z) -> None:
        from scipy.interpolate import PchipInterpolator
        xs, n1s, n2s, Y = z["xs"], z["n1s"], z["n2s"], z["Y"]
        buckets: dict[tuple, list] = {}
        for i in range(len(xs)):
            buckets.setdefault((float(n2s[i]), float(n1s[i])), []).append(i)
        self._layers = {}
        for key, idx in buckets.items():
            idx = sorted(idx, key=lambda i: float(xs[i]))
            gx = np.array([float(xs[i]) for i in idx], float)
            gy = np.array([Y[i] for i in idx], float)
            if gx.size < 2:
                continue
            self._layers[key] = {
                "x": gx, "Y": gy,
                "interp": PchipInterpolator(gx, gy, axis=0, extrapolate=False),
            }
        self._by_n1x = {}
        for (n2, n1), rec in self._layers.items():
            for xv in rec["x"]:
                self._by_n1x.setdefault((round(n1, 6), round(float(xv), 6)), []).append(n2)
        for k in self._by_n1x:
            self._by_n1x[k] = sorted(self._by_n1x[k])

    # ---------------------------------------------------------------- 拒答域
    def applicable(self, x: float, n1: float, n2: float) -> tuple[str | None, str | None]:
        """返回 `(模式, 拒答理由)`；模式为 `None` 表示**必须回退 COMSOL**。"""
        key = (round(float(x), 6), round(float(n1), 6), round(float(n2), 6))
        if key in self.quarantine:
            return None, "quarantined_pending_rerun：该角点在跨批比对中异常，已隔离"
        if n2 <= max(self.n2_fitted) + 1e-9:
            if (float(n2), float(n1)) not in self._layers:
                return None, "layer_not_in_training：(N2=%g, N1=%g) 这一层不在训练集里" % (n2, n1)
            if not (self.x_lo - 1e-9 <= float(x) <= self.x_hi + 1e-9):
                return None, ("x_outside_predictable_range：只对 x∈[%.2f, %.2f] 出值"
                              "（端点 0.20/1.00 在训练集里，属查表而非预测）" % (self.x_lo, self.x_hi))
            return "in_layer", None
        if float(n2) > self.n2_extrap_max + 1e-9:
            return None, ("n2_more_than_one_step_beyond_fitted_range：N2 只允许外推 1 步"
                          "（≤ %g）；逐步长外推未验证" % self.n2_extrap_max)
        cand = self._by_n1x.get((round(float(n1), 6), round(float(x), 6)), [])
        if len(cand) < 2:
            return None, ("fewer_than_two_n2_points_at_this_n1x：同 (N1,x) 上不足 2 个已知层，"
                          "无法定线（例如 N1=7 只存在于 N2=8）")
        if not (self.x_lo - 1e-9 <= float(x) <= self.x_hi + 1e-9):
            return None, "x_outside_predictable_range：只对 x∈[%.2f, %.2f] 出值" % (self.x_lo, self.x_hi)
        return "n2_extrap", None

    # ---------------------------------------------------------------- 预测
    def _raw(self, mode: str, x: float, n1: float, n2: float) -> np.ndarray:
        if mode == "in_layer":
            return np.asarray(self._layers[(float(n2), float(n1))]["interp"](float(x)),
                              float).ravel()
        ns = self._by_n1x[(round(float(n1), 6), round(float(x), 6))][-2:]
        ya = self._layers[(ns[0], float(n1))]["interp"](float(x))
        yb = self._layers[(ns[1], float(n1))]["interp"](float(x))
        slope = (np.asarray(yb, float) - np.asarray(ya, float)) / (ns[1] - ns[0])
        return np.asarray(yb, float) + slope * (float(n2) - ns[1])

    def _q(self, mode: str, alpha: float) -> dict:
        key = "alpha=%.2f" % alpha
        blk = (self.conformal or {}).get(mode) or {}
        if key not in blk:
            raise SurrogateUnavailable("该模式 %s 没有 α=%.2f 的校准记录 ⇒ 拒绝出区间"
                                       % (mode, alpha))
        return blk[key]

    def predict(self, x: float, n1: float, n2: float, *, alpha: float = 0.10) -> dict:
        """**唯一对外预测入口**：要么给带认证区间的曲线，要么给拒答（无数字）。"""
        base = {"model_id": self.model_id, "status": self.status,
                "data_version": self.data_version, "alpha": alpha,
                "not_a_solver": self.notice,
                "engine": "两层局部结构（层内 PCHIP + 同 (N1,x) 沿 N2 一步线性外推）"}
        if alpha not in ALLOWED_ALPHAS:
            return {**base, "accepted": False, "refused": True,
                    "reason": "alpha_not_calibrated：只校准了 %s，不得插值出未校准的区间"
                              % (list(ALLOWED_ALPHAS),)}
        mode, why = self.applicable(x, n1, n2)
        if mode is None:
            return {**base, "accepted": False, "refused": True, "reason": why,
                    "action": "请回退 COMSOL 求解（拒答域内不给任何数字）"}
        y = self._raw(mode, x, n1, n2)
        q = self._q(mode, alpha)
        qd = np.asarray(q["q_median_per_dim"], float)
        q_sim = float(q["q_simultaneous_max_over_db_dims"])
        freqs = [float(f) for f in self.spec_freqs_MHz]
        return {
            **base, "accepted": True, "refused": False, "mode": mode,
            "combo": {"x_scale": float(x), "N_w_te1": float(n1), "N_w_te2": float(n2)},
            "certified": bool(q.get("certified")),
            "freqs_MHz": freqs,
            "spl_dB": [float(v) for v in y[:N_SPEC]],
            "band_per_dim_dB": [float(v) for v in qd[:N_SPEC]],
            "band_simultaneous_dB": q_sim,
            "spl20_dB": float(y[DIM_SPL20]),
            "spl20_band_per_dim_dB": float(qd[DIM_SPL20]),
            "p20_Pa": float(y[DIM_P20]),
            "p20_band_per_dim_Pa": float(qd[DIM_P20]),
            "calibration": {
                "what": "折外绝对误差的保形分位数（对半切实测覆盖率）",
                "coverage_target": q["target"],
                "coverage_simultaneous": q.get("coverage_simultaneous"),
                "coverage_per_dim_median": float(np.median(q["coverage_mean_per_dim"])),
                "n_calibration_per_split": q["n_calibration_per_split"],
                "provenance": ("`n2_extrap` 的区间由 **7→8** 的实际外推误差标定，"
                               "用作 **8→9** 的代理——两者都是「距最高已拟合层 1 步」，"
                               "但**外推误差随步距增长的一般规律未验证**"
                               if mode == "n2_extrap" else
                               "`in_layer` 的区间由**逐层留一 x**（0.01 网格）标定"),
                "semantics": q.get("semantics"),
            },
            "usage_rule": ("逐维区间用于画误差带；要声称「整条曲线都在带内」必须用 "
                           "`band_simultaneous_dB`；`|p|` 的相对误差不可用（过零点发散），只作诊断。"),
        }

    # ---------------------------------------------------------------- 普查
    def coverage(self, *, n1_choices=(1, 2, 3, 4, 5, 6, 7, 8),
                 n2_choices=None, x_step: float = 0.01) -> dict:
        """可答域普查：给定候选网格，逐点判定接受/拒绝并给出理由分布。"""
        if n2_choices is None:
            n2_choices = list(self.n2_fitted) + [self.n2_extrap_max]
        n_x = int(round((1.00 - 0.20) / x_step)) + 1
        xs = [round(0.20 + x_step * i, 6) for i in range(n_x)]
        acc: dict[str, int] = {}
        rej: dict[str, int] = {}
        per_n2: dict[str, int] = {}
        for n2 in n2_choices:
            for n1 in n1_choices:
                for x in xs:
                    mode, why = self.applicable(x, n1, n2)
                    if mode:
                        acc[mode] = acc.get(mode, 0) + 1
                        per_n2["%g" % n2] = per_n2.get("%g" % n2, 0) + 1
                    else:
                        code = str(why).split("：")[0].split("(")[0].strip()
                        rej[code] = rej.get(code, 0) + 1
        total = sum(acc.values()) + sum(rej.values())
        return {"model_id": self.model_id, "status": self.status,
                "x_candidates": len(xs), "n1_choices": list(n1_choices),
                "n2_choices": ["%g" % v for v in n2_choices],
                "n_total": total, "n_accepted": sum(acc.values()),
                "accept_rate": (sum(acc.values()) / total) if total else None,
                "by_mode": acc, "by_reason": rej, "accepted_by_n2": per_n2,
                "x_range_predictable": [self.x_lo, self.x_hi],
                "semantics": "拒答即回退 COMSOL；拒答域内不得给任何数字"}

    # ---------------------------------------------------------------- 两点对比
    def compare(self, a: dict, b: dict, *, alpha: float = 0.10) -> dict:
        """比较两个组合：**只有差异超过同时区间才算有区分度**。"""
        pa = self.predict(a["x"], a["N1"], a["N2"], alpha=alpha)
        pb = self.predict(b["x"], b["N1"], b["N2"], alpha=alpha)
        out = {"model_id": self.model_id, "alpha": alpha, "a": pa, "b": pb}
        if not (pa.get("accepted") and pb.get("accepted")):
            out["discriminative"] = None
            out["verdict"] = "not_comparable"
            out["reason"] = ("至少一侧被拒答 ⇒ 不给比较结论（拒答即回退 COMSOL）："
                             "a=%s / b=%s" % (pa.get("reason"), pb.get("reason")))
            return out
        d_spl20 = abs(pa["spl20_dB"] - pb["spl20_dB"])
        q_sim = max(float(pa["band_simultaneous_dB"]), float(pb["band_simultaneous_dB"]))
        out["delta_spl20_dB"] = d_spl20
        out["band_simultaneous_dB"] = q_sim
        out["discriminative"] = bool(d_spl20 > q_sim)
        out["verdict"] = "有区分度" if out["discriminative"] else "无区分度（差异落在区间内）"
        out["reason"] = ("|ΔSPL20| = %.3f dB %s 同时区间 ±%.3f dB ⇒ %s"
                         % (d_spl20, ">" if out["discriminative"] else "≤", q_sim, out["verdict"]))
        # 逐频点：有多少个频点上的差异超过该点两侧区间之和
        sa = np.asarray(pa["spl_dB"], float); sb = np.asarray(pb["spl_dB"], float)
        ba = np.asarray(pa["band_per_dim_dB"], float); bb = np.asarray(pb["band_per_dim_dB"], float)
        dd = np.abs(sa - sb)
        out["n_freq_discriminative"] = int(np.sum(dd > (ba + bb)))
        out["n_freq"] = int(dd.size)
        out["freq_discriminative_rate"] = (out["n_freq_discriminative"] / out["n_freq"]
                                           if out["n_freq"] else None)
        return out

    # ---------------------------------------------------------------- DOE 预筛
    def screen(self, *, n2: float, n1_choices=(1, 2, 3, 4, 5, 6, 7),
               x_step: float = 0.01, alpha: float = 0.10, top: int = 50) -> dict:
        """给"还没算过的 N2 层"做**预筛**：按 SPL20 预测排序 + 给出区间宽度，供挑点。

        用途是**决定 COMSOL 该花在哪**，不是给答案。
        """
        n_x = int(round((1.00 - 0.20) / x_step)) + 1
        xs = [round(0.20 + x_step * i, 6) for i in range(n_x)]
        rows, refused = [], 0
        for n1 in n1_choices:
            for x in xs:
                p = self.predict(x, n1, n2, alpha=alpha)
                if not p.get("accepted"):
                    refused += 1
                    continue
                rows.append({"x_scale": x, "N_w_te1": float(n1), "N_w_te2": float(n2),
                             "spl20_dB": p["spl20_dB"],
                             "band_simultaneous_dB": p["band_simultaneous_dB"],
                             "mode": p["mode"]})
        rows.sort(key=lambda r: -r["spl20_dB"])
        return {"model_id": self.model_id, "alpha": alpha, "target_n2": float(n2),
                "n_candidates": len(rows), "n_refused": refused,
                "top": rows[:top], "all": rows,
                "usage_rule": ("这是**预筛**：用于挑选值得真跑 COMSOL 的点；"
                               "预测值不得当作结果使用，排序只在差异 > 区间时有意义。"),
                "csv": "x_scale,N_w_te1,N_w_te2,pred_spl20_dB,band_simultaneous_dB,mode\n"
                       + "\n".join("%.6f,%.6g,%.6g,%.6f,%.6f,%s"
                                   % (r["x_scale"], r["N_w_te1"], r["N_w_te2"],
                                      r["spl20_dB"], r["band_simultaneous_dB"], r["mode"])
                                   for r in rows)}

    # ---------------------------------------------------------------- 一致性哨兵
    def sentinel(self, x: float, n1: float, n2: float, *, spl20: float | None = None,
                 spectrum_dB: list[float] | None = None, alpha: float = 0.10) -> dict:
        """**新 run 的一致性哨兵**：新结果是否落在认证区间内。

        命中区间外只能报"**疑似该次求解有问题**"，**不得**自行判定谁对
        （角点异常 `(0.2,1,8)` 就是这样被发现的）。
        """
        p = self.predict(x, n1, n2, alpha=alpha)
        if not p.get("accepted"):
            return {"model_id": self.model_id, "accepted": False, "refused": True,
                    "reason": p.get("reason"),
                    "action": "该组合在拒答域内 ⇒ 无法做一致性检查（拒答即回退 COMSOL）"}
        rows, n_out = [], 0
        if spectrum_dB is not None:
            obs = np.asarray(spectrum_dB, float)
            if obs.size != N_SPEC:
                return {"model_id": self.model_id, "accepted": False,
                        "reason": "spectrum_dB 长度应为 %d，实得 %d" % (N_SPEC, obs.size)}
            pred = np.asarray(p["spl_dB"], float)
            qd = np.asarray(p["band_per_dim_dB"], float)
            dev = np.abs(obs - pred)
            inside = dev <= qd
            n_out = int((~inside).sum())
            worst = int(np.argmax(dev))
            rows = [{"freq_MHz": p["freqs_MHz"][i], "observed_dB": float(obs[i]),
                     "predicted_dB": float(pred[i]), "band_dB": float(qd[i]),
                     "deviation_dB": float(dev[i]), "inside": bool(inside[i])}
                    for i in range(N_SPEC)]
            res = {"n_out_of_band": n_out, "n_freq": N_SPEC,
                   "worst": rows[worst],
                   "engine": "spectrum"}
        elif spl20 is not None:
            dev = abs(float(spl20) - p["spl20_dB"])
            n_out = 1 if dev > p["spl20_band_per_dim_dB"] else 0
            res = {"n_out_of_band": n_out, "n_freq": 1,
                   "worst": {"freq_MHz": 20.0, "observed_dB": float(spl20),
                             "predicted_dB": p["spl20_dB"],
                             "band_dB": p["spl20_band_per_dim_dB"],
                             "deviation_dB": dev, "inside": n_out == 0},
                   "engine": "spl20"}
        else:
            return {"model_id": self.model_id, "accepted": False,
                    "reason": "必须给 `spectrum_dB`（91 点）或 `spl20` 之一"}
        verdict = ("与认证区间一致" if n_out == 0 else
                   "**超出认证区间**：疑似该次求解有问题（需从 `.mph` 核对网格/解索引后重跑）")
        return {"model_id": self.model_id, "accepted": True, "alpha": alpha,
                "combo": p["combo"], "mode": p["mode"], "verdict": verdict,
                "out_of_band": n_out > 0, **res,
                "disclaimer": ("**不得**据此自行判定哪一侧正确；本工具只报"
                               "「该点与认证区间不符」，归因需 `mesh_fingerprint` 与解索引")}

    # ---------------------------------------------------------------- 多参数网格
    def grid(self, *, n2_list, n1_max: int = 7, x_lo: float | None = None,
             x_hi: float | None = None, x_step: float = 0.01,
             alpha: float = 0.10) -> dict:
        """**多参数**批量预测：对 `N2 × N1 × x` 的完整网格逐点预测并导出 CSV。

        这是"我研究的不是单个参数"的直接答复：模型本身就是**三维参数**的
        `(x_scale, N_w_te1, N_w_te2)`，本方法把三维网格一次算完并给出每点的区间；
        拒答点单独计数（不混进结果）。
        """
        lo = self.x_lo if x_lo is None else max(float(x_lo), self.x_lo)
        hi = self.x_hi if x_hi is None else min(float(x_hi), self.x_hi)
        n = int(round((hi - lo) / x_step)) + 1
        xs = [round(lo + x_step * i, 6) for i in range(max(n, 0))]
        rows, refused, by_n2 = [], 0, {}
        for n2 in n2_list:
            acc = rej = 0
            for n1 in range(1, int(n1_max) + 1):
                for x in xs:
                    p = self.predict(x, n1, n2, alpha=alpha)
                    if not p.get("accepted"):
                        refused += 1
                        rej += 1
                        continue
                    acc += 1
                    rows.append({"x_scale": x, "N_w_te1": float(n1), "N_w_te2": float(n2),
                                 "mode": p["mode"], "spl20_dB": p["spl20_dB"],
                                 "spl20_band_dB": p["spl20_band_per_dim_dB"],
                                 "band_simultaneous_dB": p["band_simultaneous_dB"],
                                 "p20_Pa": p["p20_Pa"]})
            by_n2["%g" % n2] = {"accepted": acc, "refused": rej}
        rows.sort(key=lambda r: (r["N_w_te2"], r["N_w_te1"], r["x_scale"]))
        hdr = ("x_scale,N_w_te1,N_w_te2,engine,pred_spl20_dB,spl20_band_dB,"
               "band_simultaneous_dB,pred_p20_Pa")
        csv = hdr + "\n" + "\n".join(
            "%.6f,%.6g,%.6g,%s,%.6f,%.6f,%.6f,%.6g"
            % (r["x_scale"], r["N_w_te1"], r["N_w_te2"], r["mode"], r["spl20_dB"],
               r["spl20_band_dB"], r["band_simultaneous_dB"], r["p20_Pa"]) for r in rows)
        return {"model_id": self.model_id, "alpha": alpha,
                "n2_list": ["%g" % v for v in n2_list], "n1_max": int(n1_max),
                "x_range": [lo, hi], "x_step": x_step,
                "n_points": len(rows) + refused, "n_accepted": len(rows),
                "n_refused": refused, "by_n2": by_n2,
                "by_mode": {m: sum(1 for r in rows if r["mode"] == m)
                            for m in ("in_layer", "n2_extrap")},
                "rows": rows, "csv": csv,
                "semantics": ("每点都带认证区间（`alpha`）；`band_simultaneous_dB` 才是"
                              "「整条曲线都在带内」的界；拒答点**不给数字**、只计数。"
                              "本表是**预筛/趋势**用途，不是结果本身。"),
                "refused_note": ("拒答来自：x 端点、该层没有这个 N1、N2 超过一步外推、"
                                 "隔离角点 —— 见 `/api/surrogate/coverage` 的理由分解。")}

    # ---------------------------------------------------------------- 模型卡
    def model_card(self) -> dict:
        return {"model_id": self.model_id, "status": self.status,
                "data_version": self.data_version,
                "artifact": {"file_sha256": self.artifact_sha256,
                             "content_sha256": self.content_sha256,
                             "dir": str(self.run_dir).replace("\\", "/")},
                "structure": {"in_layer": "每个 (N2,N1) 层沿 x 的 PCHIP",
                              "n2_extrap": "同 (N1,x) 沿 N2 的一步线性外推"},
                "n2_fitted": self.n2_fitted, "n2_extrap_allowed_max": self.n2_extrap_max,
                "x_predictable": [self.x_lo, self.x_hi],
                "n_layers": len(self._layers),
                "target": {"freqs_MHz": [float(f) for f in self.spec_freqs_MHz],
                           "scalars": ["SPL20_dB", "p20_Pa"],
                           "x_axis": "频率 f (MHz)，5–50 MHz，步长 0.5 MHz，共 91 点",
                           "y_axis": "总声压级 SPL (dB re 20 µPa)，在声域点 (0,0,-1e-5)",
                           "curve_semantics": ("横轴=频率、纵轴=SPL；深蓝带=逐点 90% 区间，"
                                               "浅蓝带=同时 90% 区间（整条曲线都在带内的界）")},
                "parameters": {
                    "design_space": ["x_scale", "N_w_te1", "N_w_te2"],
                    "note": ("模型是**三维参数**的：给定 (x_scale, N1, N2) 返回一条频谱。"
                             "数据里被扫描并导出的参数**只有这三个**（导出表逐行回显的就是它们）；"
                             "要加入第四个参数必须在数据侧把它加进扫描。"),
                    "ranges": {"x_scale": [self.x_lo, self.x_hi],
                               "N_w_te1": "1 … N2−1（随层变）",
                               "N_w_te2": self.n2_fitted + [self.n2_extrap_max]},
                },
                "quarantined": [list(q) for q in self.quarantine],
                "allowed_alphas": list(ALLOWED_ALPHAS),
                "not_a_solver": self.notice,
                "red_lines": ["无场数据 ⇒ S1 场级误差界不可测 ⇒ 不得称 AI 求解器/免 COMSOL 出解",
                              "无 L1 网格收敛 ⇒ 不给工程绝对值，只谈趋势",
                              "不得声称等价于 COMSOL；放行权在人",
                              "入库需 source_type='ai_solver' + model_id + uncertainty，"
                              "且不得与 simulation 混列统计"]}
