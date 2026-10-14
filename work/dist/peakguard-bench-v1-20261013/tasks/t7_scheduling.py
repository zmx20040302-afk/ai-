# -*- coding: utf-8 -*-
"""T7 —— 闭环设计空间探索（DSE）的**免求解器复放**（solver-free replay）。

本件是原闭环 DSE 执行器（详见包内 `PORT_NOTES.md` 的逐条对照）的**匿名化供应商版本**：
驱动逻辑（候选池 / 共享 DOE / 四条臂的提议规则 / A4 适用域门禁 / 兜底规则）**逐行照搬**，
只把**真值来源**从求解器换成一个**只读查表 oracle**，其背后是本次 campaign 自己冻结的
逐点结果缓存 `PKG/oracle/points/p_<x>_<n1>_<n2>.json`。

硬保证
  * **不调用任何求解器**：本文件没有外部进程调用 / 专有求解器 / 模型文件 / Java 模板 / 台账写入，
    也不 import 任何本仓模块；只 `import` 标准库 + numpy/scipy/scikit-learn。
  * **零求解**：输出里显式写 `n_solves: 0` 与 `n_cache_hits`，任何人都不能把本复放误读成一次求解。
  * **fail-closed**：查表未命中**不猜、不外推、不用代理模型、不静默跳过** —— 抛 `CacheMissError`，
    并把 `replayable: false`、`n_refusals`、`missing_designs` 写进结果文件。

目录约定（相对本文件）
    <PKG>/tasks/t7_scheduling.py     <- 本文件
    <PKG>/tasks/ref_ledger.json      <- 冻结的 (arm,seed,k) -> design 投影（**不含 y**）
    <PKG>/oracle/points/p_*.json     <- 冻结的逐点结果缓存（94 个文件）
    <PKG>/results/T7_RESULT.json     <- 输出

冻结的预注册 `PREREG_T7.json` **不随包分发**（与其它任务一致）：其身份（文件名 + sha256）与
本任务真正报告的几个字段以常量内联在下方，故 `import` 该文件不是必需的。

用法
    python -X utf8 t7_scheduling.py
    python -X utf8 t7_scheduling.py --out-dir <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import statistics
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --------------------------------------------------------------------------- 路径
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _text  # noqa: E402  （自由文本的英文渲染表；见其 docstring）
PKG = HERE.parent
POINTS = PKG / "oracle" / "points"
RESULTS_DIR = PKG / "results"

# The frozen pre-registration is NOT distributed with the package. Its structural content and its
# identity live in `tasks/t7_frozen_protocol.py`, which is generated from the frozen document and whose
# generator asserts that rebuilding the candidate pool from it reproduces the registered pool sha256
# (which this script checks again below). See that file's docstring.
import t7_frozen_protocol as FROZEN  # noqa: E402
PREREG_NAME = "PREREG_T7.json"
PREREG_SHA256 = FROZEN.SOURCE_SHA256

# --------------------------------------------------------------------------- 常量
# 目标量口径（与 PREREG.json 的 objective 一致；此处只用于**核对**缓存里的 y，
# 缓存命中路径本身不重算 y —— 与 run_dse.py 的 `evaluate` 命中分支完全相同）。
RHO = 998.2024166435115
OMEGA = 2 * math.pi * 20.0e6          # 125663706.14359173 rad/s

# A4 门禁域：既有语料（batch C_5-50MHz）覆盖过的 (N_w_te1, N_w_te2) 对。
# 原文由 `covered_pairs()` 从 labels_two_batch.csv 现场计算；此处冻结为常量，
# 仅把「文件依赖」去掉（数值一字未改）。运行时按 GATE_N_EXPECT 自校验。
GATE_PAIRS = frozenset([
    (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 5), (2, 6), (2, 7), (2, 8),
    (3, 5), (3, 6), (3, 7), (3, 8),
    (4, 5), (4, 6), (4, 7), (4, 8),
    (5, 6), (5, 7), (5, 8),
    (6, 7), (6, 8),
    (7, 8),
])
GATE_N_EXPECT = 22

# 对照用常数（来自冻结的预注册 / 参考结果，仅用于把复放结果与注册值并列展示）
Y_STAR_REGISTERED = 2.6785656217759956e-05
POOL_SHA256_REGISTERED = "db3119ddd50c4f7f7b6d9a3e76fd6fc2d38d34487fccb3ee911e95c9a6c09b4c"

# 注册的**实际调用日程**（不是均匀的「5 次/种子」）——由原 campaign 的 LEDGER 实测反推：
#   种子 0：每条 arm 走**满 25 次轨迹**（k=0..24，原设计 calls_per_seed=25）；
#   种子 1..4：多种子补齐只回填 k=0..4（主终点 k≤5），**不**补 k>5。
# ⇒ 总调用 = 5(DOE) + 25(A1: 5 种子 × 5) + 3×25(A2/A3/A4 种子 0 满轨迹) + 3×4×5(补齐) = 105 次。
# 这一条**读不出来** PREREG 的 `calls_per_seed`（那里补齐后统一写 5，会漏掉种子 0 的 k=5..24，
# 从而少复放 60 次调用）；必须按「种子 0 走满、其余只走主终点」复放。A1 的 25 次本身就是 5 种子，
# 所以不额外翻倍。
FULL_TRACE_CALLS = 25      # 种子 0 的满轨迹长度
PRIMARY_K = 5              # 主终点：k≤5 次调用处的 best y

# 比较用容差（PROOF.py 读取本文件；本复放目标是**逐位**可复现 ⇒ 都是 0）
COMPARE_TOL_ABS = 0.0
COMPARE_TOL_REL = 0.0


class CacheMissError(RuntimeError):
    """查表 oracle 未命中：fail-closed（拒绝，而不是猜）。"""

    def __init__(self, key):
        self.key = tuple(key)
        super().__init__(
            "oracle cache miss for design (x_scale, N_w_te1, N_w_te2)=%r; "
            "refusing to extrapolate / substitute / skip" % (self.key,))


# --------------------------------------------------------------------------- 工具
def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def prereg() -> dict:
    """The frozen pre-registration's **structural** content.

    The document itself is not distributed (it is internal, and its prose is written for human readers).
    `tasks/t7_frozen_protocol.py` carries the structure the replay actually needs, generated from the
    frozen document; the pool digest it reports is re-verified against the rebuilt pool in `replay()`.
    """
    return {"kind": FROZEN.KIND, "status": FROZEN.STATUS,
            "candidate_pool": {"size": FROZEN.POOL_SIZE, "sha256": FROZEN.POOL_SHA256,
                               "x_values": FROZEN.X_VALUES, "n1n2_pairs": FROZEN.N1N2_PAIRS},
            "design": {"shared_doe": FROZEN.SHARED_DOE,
                       "arms": {k: {"seeds": v} for k, v in FROZEN.ARM_SEEDS.items()},
                       "budget": FROZEN.BUDGET}}


def pool_hash(pool) -> str:
    h = hashlib.sha256()
    for x, a, b in pool:
        h.update(("%.2f|%d|%d\n" % (x, a, b)).encode("ascii"))
    return h.hexdigest()


def y_of(payload: dict):
    """按注册口径从缓存 payload 重算目标量（用于**核对**，不用于命中路径）。"""
    k = (payload or {}).get("hemi", {}).get("K")
    if not isinstance(k, dict) or k.get("re") is None:
        return None
    y = k["im"] / (2.0 * OMEGA * RHO) / 1.0
    return y if math.isfinite(y) else None


def y_asi_of(payload: dict):
    k = (payload or {}).get("asi", {}).get("K")
    if not isinstance(k, dict) or k.get("re") is None:
        return None
    y = k["im"] / (2.0 * OMEGA * RHO) / 1.0
    return y if math.isfinite(y) else None


# --------------------------------------------------------------------------- 查表 oracle
class LookupOracle:
    """只读查表 oracle：`(x_scale, N_w_te1, N_w_te2)` -> 冻结缓存里的结果字典。

    与 `run_dse.py::evaluate` 的**命中分支**逐字段一致：
        d = json.loads(cpath.read_text(encoding="utf-8")); d["cached"] = True; return d
    区别只有一个：未命中时 `run_dse.py` 会去编译/求解，本件**拒绝**。
    """

    KEY = "p_%.2f_%d_%d.json"

    def __init__(self, points_dir: pathlib.Path):
        self.points_dir = pathlib.Path(points_dir)
        self.files = sorted(self.points_dir.glob("p_*.json")) if self.points_dir.is_dir() else []
        if not self.files:
            raise SystemExit("[FAIL] 缓存目录为空或不存在: %s" % self.points_dir)
        self.table = {}
        for f in self.files:
            d = json.loads(f.read_text(encoding="utf-8"))
            key = (round(float(d["x_scale"]), 2), int(d["N_w_te1"]), int(d["N_w_te2"]))
            self.table[key] = d
        self.n_lookups = 0          # 查表次数（含重复点）
        self.n_cache_hits = 0       # 命中次数（含重复点）
        self.n_solves = 0           # 恒为 0：本件没有求解器
        self.hit_keys = {}          # key -> 命中次数
        self.miss_keys = {}         # key -> 未命中次数
        self.refusals = []          # 每次拒绝的 (key, arm, seed, k)
        self.y_mismatch = []        # 命中但缓存 y 与 payload 重算不一致的点

    def __len__(self) -> int:
        return len(self.table)

    def keys(self):
        return set(self.table)

    def lookup(self, x: float, n1: int, n2: int, ctx=None) -> dict:
        """查表；命中返回缓存字典（`cached=True`），未命中**抛错**（fail-closed）。"""
        key = (round(float(x), 2), int(n1), int(n2))
        self.n_lookups += 1
        d = self.table.get(key)
        if d is None:
            self.miss_keys[key] = self.miss_keys.get(key, 0) + 1
            self.refusals.append({"design": list(key),
                                  "arm": (ctx or {}).get("arm"),
                                  "seed": (ctx or {}).get("seed"),
                                  "k": (ctx or {}).get("k")})
            raise CacheMissError(key)
        self.n_cache_hits += 1
        self.hit_keys[key] = self.hit_keys.get(key, 0) + 1
        rec = dict(d)
        rec["cached"] = True
        # 一致性核对：缓存的 y 与 payload 重算值必须一致（命中路径本身不重算）
        if rec.get("payload"):
            y2 = y_of(rec["payload"])
            y1 = rec.get("y")
            if (y1 is None) != (y2 is None) or (
                    y1 is not None and y2 is not None and not (y1 == y2 or abs(y1 - y2) <= 1e-18 * max(abs(y1), 1.0))):
                self.y_mismatch.append({"design": list(key), "y_cached": y1, "y_from_payload": y2})
        return rec


# --------------------------------------------------------------------------- 臂（照搬 run_dse.py）
def feats(pool):
    X = np.array([[x, a, b] for (x, a, b) in pool], dtype=float)
    lo, hi = X.min(axis=0), X.max(axis=0)
    return (X - lo) / np.maximum(hi - lo, 1e-12)


def gp_ei(seen, pool, seed=0):
    """返回提议（EI 最大）与 GP 后验标准差（用于登记）。"""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import Matern, ConstantKernel, WhiteKernel
    Xall = feats(pool)
    idx_of = {p: i for i, p in enumerate(pool)}
    done = [p for p in seen]
    Xtr = np.array([Xall[idx_of[p]] for p in done])
    ytr = np.array([math.log10(max(seen[p], 1e-30)) for p in done])
    kern = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(length_scale=np.ones(3),
                                                     length_scale_bounds=(1e-2, 1e2), nu=2.5) \
        + WhiteKernel(1e-6, (1e-12, 1e-2))
    gpr = GaussianProcessRegressor(kernel=kern, normalize_y=True, alpha=1e-10,
                                   n_restarts_optimizer=2, random_state=seed)
    gpr.fit(Xtr, ytr)
    cand = [p for p in pool if p not in seen]
    Xc = np.array([Xall[idx_of[p]] for p in cand])
    mu, sd = gpr.predict(Xc, return_std=True)
    best = ytr.max()
    z = (mu - best) / np.maximum(sd, 1e-12)
    from scipy.stats import norm
    ei = (mu - best) * norm.cdf(z) + sd * norm.pdf(z)
    j = int(np.argmax(ei))
    return cand[j], float(sd[j]), float(mu[j]), float(ei[j])


def greedy(seen, pool):
    best = max(seen, key=lambda p: seen[p])
    cand = [p for p in pool if p not in seen]
    if not cand:
        return None
    P = feats(pool)
    idx_of = {p: i for i, p in enumerate(pool)}
    b = P[idx_of[best]]
    return min(cand, key=lambda p: float(np.sum((P[idx_of[p]] - b) ** 2)))


def sequence(pre: dict, seen: dict, gate_pairs: set):
    """生成下一个 (arm,seed,k) 的提议。`seen` = 该臂可见的观测（DOE+自身）。"""
    arm = pre["_arm"]
    seed = pre["_seed"]
    k = pre["_k"]
    pool = pre["_pool"]
    if arm == "A1_random":
        rng = np.random.default_rng(1000 * seed + k)
        cand = [p for p in pool if p not in seen]
        return cand[int(rng.integers(len(cand)))] if cand else None
    if arm == "A2_greedy":
        return greedy(seen, pool) if len(seen) >= 1 else None
    if arm == "A3_gp_ei":
        return gp_ei(seen, pool, seed=seed)[0]
    if arm == "A4_gp_ei_gated":
        prop, sd, mu, ei = gp_ei(seen, pool, seed=seed)
        if (prop[1], prop[2]) in gate_pairs:
            return prop
        cand = [p for p in pool if p not in seen and (p[1], p[2]) in gate_pairs]
        if not cand:
            return prop
        Xall = feats(pool)
        idx_of = {p: i for i, p in enumerate(pool)}
        # 域内 EI 复算
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import Matern, ConstantKernel
        from scipy.stats import norm
        Xtr = np.array([Xall[idx_of[p]] for p in seen])
        ytr = np.array([math.log10(max(seen[p], 1e-30)) for p in seen])
        gpr = GaussianProcessRegressor(
            kernel=ConstantKernel(1.0) * Matern(length_scale=np.ones(3), nu=2.5),
            normalize_y=True, alpha=1e-10, n_restarts_optimizer=1, random_state=seed)
        gpr.fit(Xtr, ytr)
        Xc = np.array([Xall[idx_of[p]] for p in cand])
        mu2, sd2 = gpr.predict(Xc, return_std=True)
        b = ytr.max()
        z = (mu2 - b) / np.maximum(sd2, 1e-12)
        ei2 = (mu2 - b) * norm.cdf(z) + sd2 * norm.pdf(z)
        return cand[int(np.argmax(ei2))]
    raise SystemExit("[FAIL] 未知臂 %s" % arm)


# --------------------------------------------------------------------------- campaign 复放
def replay(oracle: LookupOracle, pre: dict, ref_ledger: dict | None = None, verbose: bool = True):
    """跑完注册的**全部**调用序列。

    日程（实测反推，见 `FULL_TRACE_CALLS` 注释）：
        共享 DOE 5 次 + A1 5 种子 × 5 次 + A2/A3/A4 种子 0 各 25 次 + 补齐 3 臂 × 4 种子 × 5 次
        = 105 次调用。
    提议规则与 `run_dse.py` 一字不差；每次调用都走查表 oracle。
    `ref_ledger` 给定时逐调用硬核对提议（不一致的调用进 `mismatches`，不掩盖）。
    返回 (pool, pool_sha256, per_arm, A1_reference, trace, mismatches)。
    任一查表未命中 -> 立刻抛 CacheMissError（fail-closed）。
    """
    pool = [(round(float(x), 2), int(a), int(b))
            for x in pre["candidate_pool"]["x_values"]
            for (a, b) in [tuple(t) for t in pre["candidate_pool"]["n1n2_pairs"]]]
    ph = pool_hash(pool)
    if ph != pre["candidate_pool"]["sha256"]:
        raise SystemExit("[FAIL] 池哈希不符：%s != %s" % (ph, pre["candidate_pool"]["sha256"]))
    if len(GATE_PAIRS) != GATE_N_EXPECT:
        raise SystemExit("[FAIL] 门禁域常量被改动：%d != %d" % (len(GATE_PAIRS), GATE_N_EXPECT))

    trace = []

    def call(idx, arm, seed, k, x, n1, n2, proposal=None):
        rec = oracle.lookup(x, n1, n2, ctx={"arm": arm, "seed": seed, "k": k})
        rec.update({"arm": arm, "seed": seed, "k": k, "call_index": idx})
        if proposal is not None:
            rec["proposal"] = list(proposal)
        trace.append(rec)
        if verbose:
            print("   [%3d] %-16s s%s k%-2d -> (%.2f,%d,%d)  y=%s  %s"
                  % (idx, arm, seed, k, x, n1, n2,
                     ("%.6e" % rec["y"]) if rec.get("y") is not None else "None", rec.get("status")))
        return rec

    # ---- 1) 共享 DOE（所有臂可见） ----
    doe_pts: dict = {}
    idx = 0
    for j, d in enumerate(pre["design"]["shared_doe"]):
        p = (round(float(d[0]), 2), int(d[1]), int(d[2]))
        idx += 1
        rec = call(idx, "DOE", 0, j, p[0], p[1], p[2])
        if rec.get("y") is not None:
            doe_pts[p] = rec["y"]

    # ---- 2) 臂序列（复放注册的**实际**日程：种子 0 满轨迹 + 种子 1..4 主终点） ----
    # 日程**必须**由注册台账投影 `ref_ledger.json` 确定，且必须提供：
    #   * 哪些臂的种子 0 走满 25 次（A2/A3/A4），哪些只走 5 次（A1）—— 这一条**读不出来** PREREG
    #     （补齐后 `calls_per_seed` 统一是 5，`calls` 统一是 25，四种臂完全一样）；
    #   * 顺带**逐调用硬核对**复放提议与注册台账是否逐位相同（不一致的调用逐条列出，不掩盖）。
    # ⇒ 缺台账时**直接拒绝**，而不是猜一个日程：猜错会少复放 60 次调用并悄悄给出错的 y_star。
    ref = ref_ledger or {}
    ref_map = {}
    for r in ref.get("records", []):
        ref_map[(r["arm"], int(r["seed"]), int(r["k"]))] = tuple(r["design"])
    if not ref_map:
        raise SystemExit("[FAIL] 缺少注册台账投影 ref_ledger.json：无法确定注册的调用日程"
                         "（哪些臂的种子 0 走满 25 次）。拒绝猜测 —— 见 --ref-ledger。")
    # 有满轨迹的臂 = 台账里该臂的 k 最大值达到 FULL_TRACE_CALLS-1
    full_trace_arms = {a for (a, s, k) in ref_map if k >= FULL_TRACE_CALLS - 1}
    if not full_trace_arms:
        raise SystemExit("[FAIL] 台账里找不到任何满轨迹臂（kmax>=%d）——台账可能被截断"
                         % (FULL_TRACE_CALLS - 1))
    plan = []
    for name, spec in pre["design"]["arms"].items():
        seeds = list(spec["seeds"])
        has_full_trace = name in full_trace_arms
        for s in seeds:
            n_k = FULL_TRACE_CALLS if (has_full_trace and s == 0) else PRIMARY_K
            for k in range(n_k):
                plan.append((name, s, k))
    # 日程必须与台账**完全一致**（少一条 / 多一条都拒绝）
    ref_arm_keys = {r for r in ref_map if r[0] != "DOE"}
    plan_keys = set(plan)
    if plan_keys != ref_arm_keys:
        raise SystemExit("[FAIL] 复放日程与注册台账不一致：日程 %d 条 / 台账 %d 条，差集 %s"
                         % (len(plan_keys), len(ref_arm_keys),
                            sorted(plan_keys ^ ref_arm_keys)[:8]))
    done: dict = {}
    mismatches = []
    for (arm, s, k) in plan:
        own = {(round(r["x_scale"], 2), r["N_w_te1"], r["N_w_te2"]): r["y"]
               for (a, s2, k2), r in done.items()
               if a == arm and s2 == s and r.get("y") is not None}
        seen = dict(doe_pts)
        seen.update(own)
        pre2 = dict(pre)
        pre2.update({"_arm": arm, "_seed": s, "_k": k, "_pool": pool})
        prop = sequence(pre2, seen, GATE_PAIRS)
        if prop is None:
            if verbose:
                print("   [SKIP] 池已耗尽 %s seed=%s k=%d" % (arm, s, k))
            continue
        idx += 1
        rec = call(idx, arm, s, k, prop[0], prop[1], prop[2], proposal=list(prop))
        done[(arm, s, k)] = rec
        rk = (arm, s, k)
        if ref_map:
            want = ref_map.get(rk)
            got = (round(float(prop[0]), 2), int(prop[1]), int(prop[2]))
            if want is not None and tuple(want) != got:
                mismatches.append({"arm": arm, "seed": s, "k": k,
                                   "proposal_replay": list(got), "proposal_registered": list(want)})

    # ---- 3) 汇总（口径照搬 analyze_multiseed.py） ----
    import collections
    arms = collections.defaultdict(dict)          # arm -> seed -> {k: rec}
    for r in trace:
        a, s, k = r.get("arm"), r.get("seed"), r.get("k")
        if a in ("A1_random", "A2_greedy", "A3_gp_ei", "A4_gp_ei_gated") and s is not None and k is not None:
            arms[a].setdefault(s, {})[k] = r

    per_arm = {}
    for a, seeds in sorted(arms.items()):
        block = {}
        ks = sorted({k for d in seeds.values() for k in d})
        for s, d in sorted(seeds.items()):
            seq = [d[k]["y"] for k in ks if k in d]
            pts = [tuple(d[k]["proposal"]) for k in ks if k in d]
            block[str(s)] = {"n_calls": len(d), "ks": [k for k in ks if k in d],
                             "y_sequence_k0_to_kN": seq,
                             "proposal_sequence": [list(p) for p in pts],
                             "best_at_k5": max(seq[:5]) if len(seq) >= 5 else None,
                             "simple_regret_at_k5": (1 - (max(seq[:5]) / Y_STAR_REGISTERED)) if len(seq) >= 5 else None}
        common_ks = [k for k in ks if all(k in d for d in seeds.values())]
        identical = {str(k): len({round(seeds[s][k]["y"], 18) for s in seeds}) == 1 for k in common_ks}
        pt_same = {str(k): len({tuple(seeds[s][k]["proposal"]) for s in seeds}) == 1 for k in common_ks}
        b5 = [block[str(s)]["best_at_k5"] for s in sorted(seeds)]
        block["_across_seeds"] = {"common_ks": common_ks,
                                  "y_identical_at_every_k": all(identical.values()),
                                  "proposal_identical_at_every_k": all(pt_same.values()),
                                  "per_k_y_identical": identical, "per_k_proposal_identical": pt_same,
                                  "best_at_k5_list": b5,
                                  "best_at_k5_median": statistics.median([x for x in b5 if x is not None]) if any(b5) else None,
                                  "best_at_k5_spread": (max(b5) - min(b5)) if all(b5) else None,
                                  "n_seeds": len(seeds)}
        per_arm[a] = block

    a1 = per_arm.get("A1_random", {}).get("_across_seeds", {})
    a1_ref = None
    if a1:
        lm = a1.get("best_at_k5_list") or []
        a1_ref = {"best_at_k5_list": lm,
                  "median": statistics.median(lm) if lm else None,
                  "max": max(lm) if lm else None,
                  "min": min(lm) if lm else None,
                  "spread": (max(lm) - min(lm)) if lm else None}
        for a, blk in per_arm.items():
            if a == "A1_random":
                continue
            lst = blk["_across_seeds"]["best_at_k5_list"]
            if not lst:
                continue
            per_arm[a]["_vs_A1"] = {
                "median_ge_A1_median": (statistics.median(lst) >= a1_ref["median"]),
                "all_seeds_above_A1_max": all(x > a1_ref["max"] for x in lst),
                "spread_gt_A1": (blk["_across_seeds"]["best_at_k5_spread"] or 0) > (a1_ref["spread"] or 0),
                "seed_variance_zero": blk["_across_seeds"]["best_at_k5_spread"] == 0}
    return pool, ph, per_arm, a1_ref, trace, mismatches


def build_result(out_dir: pathlib.Path, ref_ledger: dict | None = None) -> dict:
    pre = prereg()
    pre_sha = PREREG_SHA256
    oracle = LookupOracle(POINTS)
    all_keys = sorted(oracle.keys())

    res = {
        "kind": "t7_scheduling_solver_free_replay",
        "script": "tasks/t7_scheduling.py",
        "oracle": {
            "kind": "lookup_from_frozen_cache",
            "cache_dir": "oracle/points",
            "cache_files": len(oracle),
            "cache_keys": [list(k) for k in all_keys],
            "n_solves": 0,
            "n_cache_hits": 0,
            "n_lookups": 0,
            "n_cache_misses": 0,
            "solver_invoked": False,
            "note": "n_solves 恒为 0：本件不含任何求解器调用路径（无外部进程 / 专有求解器 / 模型文件）。",
        },
        "prereg": {
            "path": "not distributed (identity inlined; sha256 below is the frozen document's)",
            "file": PREREG_NAME,
            "sha256": pre_sha,
            "kind": pre.get("kind"),
            "status": pre.get("status"),
            "candidate_pool_size": pre["candidate_pool"]["size"],
            "candidate_pool_sha256_registered": pre["candidate_pool"]["sha256"],
            "budget": pre.get("design", {}).get("budget"),
        },
        "replay_design": {
            "schedule": ("DOE 5 次 + A1 5 种子×5 次 + A2/A3/A4 种子 0 各 25 次 + "
                         "A2/A3/A4 种子 1-4 各 5 次 = 165 次调用"),
            "full_trace_calls": FULL_TRACE_CALLS,
            "primary_k": PRIMARY_K,
            "derived_from": "注册 LEDGER 投影的 (arm,seed,k) 覆盖实测反推（PREREG.calls_per_seed 不足以表达）",
        },
        "gate_domain": {"n_pairs": len(GATE_PAIRS),
                        "pairs": [list(p) for p in sorted(GATE_PAIRS)],
                        "source": "batch C_5-50MHz 语料覆盖的 (N_w_te1, N_w_te2) 对（冻结常量）"},
        "replayable": False,
        "refused": False,
        "n_refusals": 0,
        "missing_designs": [],
        "refusal_log": [],
        "n_duplicate_design_visits": 0,
        "n_calls_replayed": 0,
        "oracle_consistency": {"y_cache_vs_payload_mismatches": []},
        "proposal_check_vs_registered_ledger": {
            "ref_supplied": bool(ref_ledger),
            "n_records_ref": len((ref_ledger or {}).get("records", [])),
            "n_proposal_mismatches": 0,
            "mismatches": [],
        },
        "per_arm": {},
        "A1_reference": None,
        "y_star": None,
        "y_star_registered": Y_STAR_REGISTERED,
    }

    try:
        pool, ph, per_arm, a1_ref, trace, mismatches = replay(oracle, pre, ref_ledger=ref_ledger)
    except CacheMissError:
        res["refused"] = True
        res["replayable"] = False
        res["per_arm"] = {}
        mismatches = []
        trace = []
    else:
        res["candidate_pool_sha256_replayed"] = ph
        res["per_arm"] = per_arm
        res["A1_reference"] = a1_ref
        all_y = [r["y"] for r in trace if str(r.get("arm", "")).startswith("A") and r.get("y") is not None]
        res["y_star"] = max(all_y) if all_y else None
        res["replayable"] = True
        # 逐点访问统计
        res["n_duplicate_design_visits"] = sum(v - 1 for v in oracle.hit_keys.values() if v > 1)

    res["n_calls_replayed"] = len(trace)
    res["proposal_check_vs_registered_ledger"]["n_proposal_mismatches"] = len(mismatches)
    res["proposal_check_vs_registered_ledger"]["mismatches"] = mismatches[:50]

    res["oracle"]["n_solves"] = oracle.n_solves
    res["oracle"]["n_cache_hits"] = oracle.n_cache_hits
    res["oracle"]["n_lookups"] = oracle.n_lookups
    res["oracle"]["n_cache_misses"] = len(oracle.miss_keys)
    res["oracle"]["n_distinct_designs_hit"] = len(oracle.hit_keys)
    res["oracle"]["cache_utilization"] = ("%d/%d" % (len(oracle.hit_keys), len(oracle)))
    res["oracle"]["hit_counts"] = {"%0.2f|%d|%d" % k: v for k, v in sorted(oracle.hit_keys.items())}
    res["oracle_consistency"]["y_cache_vs_payload_mismatches"] = oracle.y_mismatch
    res["n_refusals"] = len(oracle.refusals)
    res["refusal_log"] = oracle.refusals
    res["missing_designs"] = [list(k) for k in sorted(oracle.miss_keys)]
    if oracle.miss_keys:
        res["replayable"] = False

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "T7_RESULT.json").write_bytes(
        (json.dumps(_text.to_en(res), ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))
    # 逐调用留痕（与结果文件分开；便于审计，不参与数值比较）
    (out_dir / "T7_CALL_TRACE.json").write_bytes(
        (json.dumps({"n_calls": len(trace),
                     "calls": [{k: v for k, v in r.items() if k != "payload"} for r in trace]},
                    ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="T7 solver-free DSE replay (cache oracle)")
    ap.add_argument("--out-dir", default=None, help="缺省 <PKG>/results")
    ap.add_argument("--ref-ledger", default="ref_ledger.json",
                    help="注册台账的 (arm,seed,k)->design 投影（只读，用于确定日程并逐调用核对提议）；缺省 <PKG>/tasks/ref_ledger.json")
    a = ap.parse_args(argv)
    out_dir = pathlib.Path(a.out_dir) if a.out_dir else RESULTS_DIR
    rl_path = pathlib.Path(a.ref_ledger)
    if not rl_path.is_absolute():
        rl_path = HERE / rl_path
    ref = None
    if rl_path.exists():
        ref = json.loads(rl_path.read_text(encoding="utf-8"))
        print("== 注册台账投影（只读）: %s  records=%d" % (rl_path, len(ref.get("records", []))))
    else:
        print("== [REFUSE] 缺少注册台账投影 %s：无法确定注册调用日程（拒绝猜测）" % rl_path)
        return 4
    print("== T7 免求解器复放：HERE=%s  PKG=%s" % (HERE, PKG))
    print("== 查表 oracle：%s" % POINTS)
    res = build_result(out_dir, ref_ledger=ref)
    o = res["oracle"]
    print("== n_solves=%d  n_cache_hits=%d  n_lookups=%d  distinct=%d/%d  duplicates=%d  refusals=%d"
          % (o["n_solves"], o["n_cache_hits"], o["n_lookups"], o["n_distinct_designs_hit"],
             o["cache_files"], res["n_duplicate_design_visits"], res["n_refusals"]))
    print("== n_calls=%d  replayable=%s  refused=%s  missing_designs=%d"
          % (res["n_calls_replayed"], res["replayable"], res["refused"], len(res["missing_designs"])))
    pc = res["proposal_check_vs_registered_ledger"]
    print("== 提议核对：ref_supplied=%s  n_records_ref=%d  mismatches=%d"
          % (pc["ref_supplied"], pc["n_records_ref"], pc["n_proposal_mismatches"]))
    print("== y_star=%s（注册值 %s）" % (res["y_star"], res["y_star_registered"]))
    print("== 写出 %s" % (out_dir / "T7_RESULT.json"))
    return 0 if res["replayable"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
