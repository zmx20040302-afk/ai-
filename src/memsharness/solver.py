# -*- coding: utf-8 -*-
"""AI 求解器（免 COMSOL 出解）的**底层配置层**：规格校验、S 级评估、放行状态机、出解与盖章。

用户 2026-09-30 指示：「先完成求解器的底层配置，场级解我正在导出」——
即**在场数据到达之前**，把接收它的那一层配好、并用可离线检验的方式锁死。

本模块把三份权威口径落成代码，**不新增第四套口径**：
* `WORKING_PLAN.md` §6.1.1（S0–S5 指标与阈值）与 §6.4（放行门禁 + 运行时强制规则）；
* 技能 `ai-solver-verification`（S3 硬门禁、保形误差界、状态机）；
* 技能 `field-io-contract`（公共点集、掩膜、场级相对 L2 定义）。

### 三条不可协商的行为（都有用例守着）

1. **代码不得自我放行**。`draft → physics_consistent → solver_certified` 可由代码依据
   S 级证据推进；但 `→ approved_solver`（以及从 `suspended` 恢复）**必须有人签字**
   （`sign_off.by` 非空且给出适用范围），否则拒绝跃迁。这与红线 5「人保留放行权」一致。
2. **`None`（无法判定）≠ 通过**。S3 任一检查为 `None` ⇒ 整体 `inconclusive`，
   状态**不许**推进；S5 未认证时 `s5_passed = None`（不是 True）。这是 S3 硬门禁的原文语义。
3. **未放行不得出解**。`solve()` 只在状态为 `approved_solver` 且参数**命中适用范围**时给场；
   否则返回 `refused=True` + 回退 COMSOL 的理由（§6.4 运行时规则）。
   每次出解都附 **场级误差界 + 验证等级 + 适用范围命中情况**，并盖 `source_type='ai_solver'`。
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any, Iterable, Sequence

REPO = pathlib.Path(__file__).resolve().parents[2]
SOLVER_ROOT = REPO / "work/runs/solver"


def solver_root() -> pathlib.Path:
    """放行台账根目录：env 覆盖 > 测试期临时目录 > 生产（沿用仓库既有的三级优先）。"""
    import os
    import tempfile
    env = os.environ.get("MEMS_SOLVER_ROOT")
    if env:
        return pathlib.Path(env)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return pathlib.Path(tempfile.gettempdir()) / "memshop-solver-under-test"
    return SOLVER_ROOT

#: §6.4 的状态机（**顺序即门禁顺序**；`suspended` 是任一阶段都可能落入的降级态）
STATES: tuple[str, ...] = ("draft", "physics_consistent", "solver_certified",
                           "approved_solver", "suspended")

#: 代码可依据证据自动完成的跃迁（不涉及"放行"这一人类决定）
AUTO_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("draft", "physics_consistent"),
    ("physics_consistent", "solver_certified"),
    ("physics_consistent", "suspended"),
    ("solver_certified", "suspended"),
    ("approved_solver", "suspended"),
)
#: **必须人工签字**的跃迁（红线 5：放行权在人）
HUMAN_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("solver_certified", "approved_solver"),
    ("suspended", "physics_consistent"),
    ("suspended", "solver_certified"),
)

#: §6.1.1 的默认阈值（可被 spec 覆盖；**缺一项即拒绝加载**——不许用"我记得的"默认值兜底）
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "S0_limit_rel_err_max": 0.01,        # 极限一致性 < 1%
    "S1_key_region_rel_L2_max": 0.02,    # 关键区域 < 2%
    "S1_global_rel_L2_max": 0.05,        # 全域 ≤ 5%
    "S2_engineering_rel_err_max": 0.03,  # 工程量 < 3%
    "S3_conservation_residual_max": 0.005,   # 守恒残差 < 0.5%
    "S3_bc_residual_max": 0.01,          # BC 残差 < 1%
    "S4_mesh_diff_max": 0.02,            # 网格无关性 < 2%
    "S5_coverage_min": 0.85,             # 90% 界覆盖率 85–95%
    "S5_coverage_max": 0.95,
}

#: 加载 spec 时**必须**出现的顶层键（少一个就 fail-closed，不允许"跑起来再说"）
REQUIRED_KEYS: tuple[str, ...] = (
    "solver_id", "method", "fields", "point_set", "applicability",
    "thresholds", "state", "stamps",
)
#: 给出解时必须齐备的元数据（§6.4 运行时规则 + 红线 7）
REQUIRED_STAMPS: tuple[str, ...] = (
    "source_type", "model_id", "uncertainty", "verification_level", "applicability_hit",
)


class SpecError(ValueError):
    """规格不合法。**一律拒绝**，不做"尽力而为"的修补。"""


# ---------------------------------------------------------------------------
# 规格加载与校验
# ---------------------------------------------------------------------------
def load_spec(path: str | pathlib.Path) -> dict:
    """读 solver_spec（YAML/JSON 皆可）并**严格校验**。"""
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = REPO / p
    if not p.is_file():
        raise SpecError("solver_spec 不存在：%s" % p)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml
        spec = yaml.safe_load(text)
    else:
        spec = json.loads(text)
    if not isinstance(spec, dict):
        raise SpecError("solver_spec 顶层必须是映射")
    validate_spec(spec)
    spec["_path"] = str(p)
    return spec


def validate_spec(spec: dict) -> None:
    """fail-closed 校验：缺键、状态非法、阈值不全、点集/掩膜策略不明 —— 全部拒绝。

    **一次性报全部缺口**（不中途 return）：配置是给人填的，一次只报一条会让人反复试错；
    而"报全"不会放松 fail-closed —— 只要有一条不满足就仍然拒绝加载。
    """
    bad: list[str] = []

    miss = [k for k in REQUIRED_KEYS if k not in spec]
    if miss:
        bad.append("缺必需键：%s" % ", ".join(miss))
    if spec.get("state") not in STATES:
        bad.append("state 非法：%r（合法值 %s）" % (spec.get("state"), "/".join(STATES)))
    if not spec.get("solver_id"):
        bad.append("solver_id 不能为空")
    if str(spec.get("method", "")).lower() not in ("pod", "rom", "pod-rom"):
        bad.append("method 只支持降阶路线（pod/rom）；深度算子路线尚未接入（§1 首选路线）")

    fields = spec.get("fields")
    if not isinstance(fields, list) or not fields:
        bad.append("fields 必须是非空列表（每个场要有名字与单位）")
    else:
        for f in fields:
            if not isinstance(f, dict) or not f.get("name") or not f.get("unit"):
                bad.append("每个 field 必须给 name 与 unit（单位一律 SI，见 field-io-contract）")
                break

    ps = spec.get("point_set")
    if not isinstance(ps, dict) or not ps.get("spec") or "points_file" not in ps:
        bad.append("point_set 必须给 spec 与 points_file"
                   " —— 公共点集必须**在接入阶段就定好**（field-io-contract §1/§7）")
    elif str(ps.get("mask_policy", "")) != "common_mask_all_finite":
        bad.append("point_set.mask_policy 必须是 common_mask_all_finite"
                   "（公共掩膜 = 在所有快照中都有限的点；绝不允许把 NaN 当 0）")

    thr = spec.get("thresholds")
    if not isinstance(thr, dict):
        bad.append("thresholds 必须是映射")
    else:
        mt = [k for k in DEFAULT_THRESHOLDS if k not in thr]
        if mt:
            bad.append("thresholds 缺项（不许用默认值兜底，那会变成第二套口径）：%s"
                       % ", ".join(mt))

    app = spec.get("applicability")
    if not isinstance(app, dict):
        bad.append("applicability 必须是映射")
    elif not app.get("param_bounds"):
        bad.append("applicability.param_bounds 必填（没有适用范围的求解器等于无界外推）")

    st = spec.get("stamps")
    if not isinstance(st, dict):
        bad.append("stamps 必须是映射")
    else:
        ms = [k for k in REQUIRED_STAMPS if k not in st]
        if ms:
            bad.append("stamps 缺项：%s" % ", ".join(ms))
        if st.get("source_type") != "ai_solver":
            bad.append("stamps.source_type 必须是 'ai_solver'（红线 8：AI 解是独立来源）")

    rel = spec.get("release") or {}
    if rel.get("state") and rel["state"] != spec.get("state"):
        bad.append("spec.state 与 release.state 不一致（只留一个口径）")

    if bad:
        raise SpecError("solver_spec 有 %d 处不合法（全部列出，逐条修完再加载）：\n  - %s"
                        % (len(bad), "\n  - ".join(bad)))


def new_spec_template(*, solver_id: str, model_id: str = "", fields: Sequence[dict] = (),
                      point_set_spec: dict | None = None,
                      points_file: str = "share/pod_points.txt") -> dict:
    """产出一个**草稿**规格（state=draft）。默认阈值取自 §6.1.1，便于人逐项确认。"""
    return {
        "solver_id": solver_id,
        "method": "pod",
        "model_id": model_id,
        "fields": list(fields) or [{"name": "u", "unit": "m"}],
        "point_set": {
            "spec": point_set_spec or {"note": "待由场导出确定：每轴 start/stop/n"},
            "points_file": points_file,
            "mask_policy": "common_mask_all_finite",
        },
        "applicability": {
            "geometry_family": "",
            "param_bounds": {},
            "frequency_range_MHz": [5.0, 50.0],
            "extrapolation": {"allowed_steps": 0, "policy": "一步以上外推一律拒答"},
        },
        "thresholds": dict(DEFAULT_THRESHOLDS),
        "state": "draft",
        "stamps": {k: ("" if k != "source_type" else "ai_solver") for k in REQUIRED_STAMPS},
        "recheck": {"every_n_solves": 200, "every_hours": 168, "action_on_drift": "suspended"},
        "release": {"state": "draft", "history": []},
        "schedule": "按 §6.4：定期抽样用 COMSOL 复检；命中漂移 → suspended",
    }


# ---------------------------------------------------------------------------
# S0–S5 评估（None 一律不等于通过）
# ---------------------------------------------------------------------------
def _thr(spec: dict, key: str) -> float:
    return float(spec["thresholds"][key])


def _level(name: str, checks: list[tuple[str, bool | None, str]]) -> dict:
    """把一个等级的所有检查合成结论。**任一 None 且其余全 True ⇒ inconclusive（不通过）**。"""
    vals = [c[1] for c in checks]
    if any(v is False for v in vals):
        verdict = "failed"
    elif any(v is None for v in vals):
        verdict = "inconclusive"
    else:
        verdict = "passed"
    return {"level": name, "verdict": verdict, "passed": verdict == "passed",
            "checks": [{"name": n, "ok": ok, "note": note} for n, ok, note in checks]}


def evaluate_levels(spec: dict, evidence: dict) -> dict:
    """按 §6.1.1 评估 S0–S5。`evidence` 缺项 ⇒ 该检查 `None` ⇒ 该级 inconclusive。

    期望的 `evidence` 结构（缺哪项就标 `None`，**不要填占位数字**）：
      s0_limit_rel_err: float
      s1: {"key_region_rel_L2_max": float, "global_rel_L2_max": float,
           "n_holdout": int, "is_independent": bool}
      s2: {"engineering_rel_err": {name: float, ...}}
      s3: evaluate_s3(...) 的结果（dict，含 verdict）
      s4: {"mesh_diff_max": float, "n_meshes": int}
      s5: {"coverage": float, "n_calibration": int, "certified": bool}
    """
    ev = evidence or {}
    out: dict[str, Any] = {"levels": {}, "evidence_keys": sorted(ev)}

    # S0 —— 极限一致性
    v = ev.get("s0_limit_rel_err")
    out["levels"]["S0"] = _level("S0", [(
        "极限下相对误差 < %.3g" % _thr(spec, "S0_limit_rel_err_max"),
        None if v is None else float(v) < _thr(spec, "S0_limit_rel_err_max"),
        "未提供 s0_limit_rel_err" if v is None else "rel_err=%.4g" % float(v))])

    # S1 —— 场级相对 L2（独立留出集！）
    s1 = ev.get("s1") or {}
    checks = []
    for key, thr_key, label in (
            ("key_region_rel_L2_max", "S1_key_region_rel_L2_max", "关键区域"),
            ("global_rel_L2_max", "S1_global_rel_L2_max", "全域")):
        x = s1.get(key)
        checks.append(("%s 相对 L2 < %.3g" % (label, _thr(spec, thr_key)),
                       None if x is None else float(x) <= _thr(spec, thr_key),
                       "未提供" if x is None else "%.4g" % float(x)))
    n_h = s1.get("n_holdout")
    indep = s1.get("is_independent")
    checks.append(("留出集非空且独立于训练点",
                   None if (n_h is None or indep is None) else bool(int(n_h) > 0 and indep),
                   "n_holdout=%s is_independent=%s" % (n_h, indep)))
    out["levels"]["S1"] = _level("S1", checks)

    # S2 —— 工程量误差（逐个报，不做平均掩盖）
    s2 = ev.get("s2") or {}
    eng = s2.get("engineering_rel_err") or {}
    caps = _thr(spec, "S2_engineering_rel_err_max")
    if not eng:
        out["levels"]["S2"] = _level("S2", [("工程量相对误差 < %.3g" % caps, None, "未提供")])
    else:
        out["levels"]["S2"] = _level("S2", [
            ("%s < %.3g" % (k, caps), float(v) < caps, "%.4g" % float(v))
            for k, v in sorted(eng.items())])

    # S3 —— 物理一致性（**硬门禁**：交给 consistency.evaluate_s3 判，None 不算通过）
    s3 = ev.get("s3")
    if isinstance(s3, dict) and "verdict" in s3:
        out["levels"]["S3"] = {"level": "S3", "verdict": s3["verdict"],
                               "passed": s3["verdict"] == "passed",
                               "checks": s3.get("checks", []),
                               "note": s3.get("note", "")}
    else:
        out["levels"]["S3"] = _level("S3", [("物理一致性检查", None, "未提供 s3 结果")])

    # S4 —— 离散无关性
    s4 = ev.get("s4") or {}
    v4 = s4.get("mesh_diff_max")
    n4 = s4.get("n_meshes")
    out["levels"]["S4"] = _level("S4", [
        ("2–3 套网格上差异 < %.3g" % _thr(spec, "S4_mesh_diff_max"),
         None if v4 is None else float(v4) < _thr(spec, "S4_mesh_diff_max"),
         "未提供" if v4 is None else "%.4g" % float(v4)),
        ("网格套数 ≥ 2", None if n4 is None else int(n4) >= 2, "n_meshes=%s" % n4)])

    # S5 —— 误差界校准（覆盖率 + **保形认证**；未认证 ⇒ None，不是 True）
    # SOP §4 原文：「未认证时 s5_passed = null（不是 True）」⇒
    # `certified=False` 是**无法判定**，不是"检查失败"：把它记成 failed 会让人以为
    # "误差界不能用"，而真相是"样本还不够，先别放行"。
    s5 = ev.get("s5") or {}
    cov, ncal, cert = s5.get("coverage"), s5.get("n_calibration"), s5.get("certified")
    nho = s5.get("n_holdout")      # 可选的覆盖率评估点数
    lo, hi = _thr(spec, "S5_coverage_min"), _thr(spec, "S5_coverage_max")
    # 覆盖率在 n 个评估点上只能取 k/n —— 若**没有任何 k/n 落在 [lo, hi] 内**，
    # 这条判据在本次评估规模下**不可达**，必须记"无法判定"（None）而不是 failed：
    # 记 failed 会把"点太少"误报成"误差界不达标"（错误归因，实测 n=5 时
    # [0.85,0.95] 在 {0,0.2,…,1.0} 上根本取不到，真值 coverage=1.0 被记成 failed）。
    cov_ok = None if cov is None else (lo <= float(cov) <= hi)
    cov_note = "未提供" if cov is None else "coverage=%.4g" % float(cov)
    if cov is not None and nho:
        n_h = int(nho)
        if not any(lo <= (k / n_h) <= hi for k in range(n_h + 1)):
            cov_ok = None
            cov_note += ("；⚠️ n_holdout=%d ⇒ 覆盖率只能取 k/%d（步长 %.2f），"
                         "[%.2f, %.2f] 其上不可达 ⇒ 本项无法判定（分辨率不足，非不达标）"
                         % (n_h, n_h, 1.0 / n_h, lo, hi))
            out.setdefault("notes", []).append(
                "S5 覆盖率判据因评估点分辨率不足不可达（n_holdout=%d）⇒ inconclusive" % n_h)
    out["levels"]["S5"] = _level("S5", [
        ("90%% 界覆盖率落在 [%.2f, %.2f]" % (lo, hi), cov_ok, cov_note),
        ("误差界已认证（校准点足够）",
         None if (cert is None or cert is False) else True,
         "certified=%s n_calibration=%s" % (cert, ncal))])
    _v5 = out["levels"]["S5"]["verdict"]
    out["s5_passed"] = True if _v5 == "passed" else (None if _v5 == "inconclusive" else False)
    return out


# ---------------------------------------------------------------------------
# 放行状态机（**代码不得自我放行**）
# ---------------------------------------------------------------------------
def next_state(spec: dict, levels: dict, *, sign_off: dict | None = None,
               drift_detected: bool = False) -> dict:
    """依据 S 级结论给出**建议的**下一状态与理由；不做任何写入。

    规则（§6.4）：
      * S3 失败 ⇒ 不得进入 `physics_consistent`（硬门禁）；
      * S3 inconclusive（含 None）⇒ 停在原地（`None ≠ 通过`）；
      * S0/S3 通过 ⇒ 可 `physics_consistent`；
      * S1/S2 达标 + S5 通过 + 独立留出集 ⇒ 可 `solver_certified`；
      * `approved_solver` **只认人工签字**（`sign_off.by` + `scope`）；
      * 漂移 ⇒ `suspended`。
    """
    cur = spec["state"]
    L = {k: v.get("verdict") for k, v in levels.items()}

    if drift_detected:
        if cur == "suspended":
            return {"from": cur, "to": cur, "allowed": False,
                    "reason": "已在 suspended；再放行需人工复核 + 重新认证"}
        return {"from": cur, "to": "suspended", "allowed": True,
                "auto": True, "reason": "漂移复检失败 ⇒ 降级 suspended（§6.4）"}

    if cur == "suspended":
        so = sign_off or {}
        if so.get("by") and so.get("scope"):
            return {"from": cur, "to": "physics_consistent", "allowed": True, "auto": False,
                    "reason": "人工签字恢复：%s（适用范围 %s）" % (so["by"], so["scope"])}
        return {"from": cur, "to": cur, "allowed": False,
                "reason": "suspended 状态**只能由人**恢复（需 sign_off.by 与 scope）"}

    if cur == "draft":
        if L.get("S3") == "passed" and L.get("S0") == "passed":
            return {"from": cur, "to": "physics_consistent", "allowed": True, "auto": True,
                    "reason": "S0 与 S3 均通过（§6.4 第一道门）"}
        bad = {k: v for k, v in L.items() if k in ("S0", "S3") and v != "passed"}
        return {"from": cur, "to": cur, "allowed": False,
                "reason": "S0/S3 未全过（%s）⇒ 不得进入 physics_consistent（S3 是硬门禁，"
                          "None=无法判定也不算通过）" % json.dumps(bad, ensure_ascii=False)}

    if cur == "physics_consistent":
        need = {"S1": "passed", "S2": "passed", "S5": "passed"}
        bad = {k: L.get(k) for k, v in need.items() if L.get(k) != v}
        if not bad:
            return {"from": cur, "to": "solver_certified", "allowed": True, "auto": True,
                    "reason": "S1/S2 达标 + S5 已认证 + 独立留出集（§6.4 第二道门）"}
        return {"from": cur, "to": cur, "allowed": False,
                "reason": "S1/S2/S5 未全过（%s）⇒ 不得进入 solver_certified"
                          % json.dumps(bad, ensure_ascii=False)}

    if cur == "solver_certified":
        so = sign_off or {}
        if not so.get("by"):
            return {"from": cur, "to": cur, "allowed": False, "needs_human": True,
                    "reason": "**代码不得自我放行**：approved_solver 需要人工签字"
                              "（sign_off.by）与适用范围（sign_off.scope）"}
        if not so.get("scope"):
            return {"from": cur, "to": cur, "allowed": False, "needs_human": True,
                    "reason": "人工签字必须同时给出适用范围 scope（§6.4 第 3 条硬条件）"}
        return {"from": cur, "to": "approved_solver", "allowed": True, "auto": False,
                "reason": "人工放行：%s；适用范围 %s" % (so["by"], so["scope"])}

    if cur == "approved_solver":
        return {"from": cur, "to": cur, "allowed": False,
                "reason": "已是 approved_solver；无漂移则不跃迁"}
    raise ValueError("未知状态：%r" % cur)


def apply_state(spec_path: str | pathlib.Path, *, sign_off: dict | None = None,
                drift_detected: bool = False, levels: dict | None = None,
                evidence: dict | None = None, write: bool = False) -> dict:
    """算下一状态；`write=True` 时**追加**一条放行台账（append-only）并回写 spec 的 state。

    台账：`work/runs/solver/<solver_id>/release_log.jsonl`（只追加，不覆盖）。
    ⚠️ 回写 spec 只改 `state` 与 `release.history` 两项；其余字段原样保留。
    """
    spec = load_spec(spec_path)
    lv = levels or evaluate_levels(spec, evidence or {})
    nxt = next_state(spec, lv.get("levels", {}), sign_off=sign_off,
                     drift_detected=drift_detected)
    nxt["levels"] = {k: v.get("verdict") for k, v in (lv.get("levels") or {}).items()}
    if not write:
        return nxt
    if not nxt.get("allowed"):
        return {**nxt, "written": False}

    p = pathlib.Path(spec_path)
    if not p.is_absolute():
        p = REPO / p
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "solver_id": spec["solver_id"],
           "from": nxt["from"], "to": nxt["to"], "auto": bool(nxt.get("auto")),
           "levels": nxt["levels"], "reason": nxt["reason"],
           "sign_off": sign_off or None}
    d = solver_root() / str(spec["solver_id"])
    d.mkdir(parents=True, exist_ok=True)
    with (d / "release_log.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if nxt["to"] != spec["state"]:
        spec["state"] = nxt["to"]
        rel = spec.setdefault("release", {"state": nxt["to"], "history": []})
        rel["state"] = nxt["to"]
        rel.setdefault("history", []).append(rec)
        spec.pop("_path", None)
        text = json.dumps(spec, ensure_ascii=False, indent=1) + "\n"
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml
            text = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)
        p.write_text(text, encoding="utf-8", newline="\n")
    return {**nxt, "written": True, "ledger": str((d / "release_log.jsonl"))}


# ---------------------------------------------------------------------------
# 适用范围（OOD）与出解
# ---------------------------------------------------------------------------
def applicability(spec: dict, params: dict) -> dict:
    """逐条判参数是否落在已声明适用范围内。**任何一条不满足 ⇒ 拒答 + 回退 COMSOL。**"""
    app = spec.get("applicability") or {}
    misses: list[dict] = []
    hits: list[str] = []
    bounds = app.get("param_bounds") or {}
    for name, rng in bounds.items():
        if name not in params:
            misses.append({"what": "缺参数", "name": name, "why": "适用范围声明了该参数"})
            continue
        lo, hi = (rng if isinstance(rng, (list, tuple)) else (rng, rng))
        v = params[name]
        if v is None or float(v) < float(lo) or float(v) > float(hi):
            misses.append({"what": "越界", "name": name, "value": v,
                           "range": [lo, hi]})
        else:
            hits.append(name)
    fam = app.get("geometry_family")
    if fam:
        got = params.get("geometry_family")
        if got is None:
            misses.append({"what": "缺几何族", "name": "geometry_family",
                           "why": "跨越几何族的外推一律拒答"})
        elif str(got) != str(fam):
            misses.append({"what": "族不匹配", "name": "geometry_family",
                           "value": got, "expected": fam})
        else:
            hits.append("geometry_family")
    return {"applicable": not misses, "hits": hits, "misses": misses,
            "action": "predict" if not misses else "refuse_and_fallback_comsol",
            "declared": {"param_bounds": bounds, "geometry_family": fam,
                         "frequency_range_MHz": app.get("frequency_range_MHz")}}


def stamp(spec: dict, *, uncertainty: Any, verification_level: str | None = None,
          applicability_result: dict | None = None) -> dict:
    """出解的**必带元数据**（§6.4 + 红线 7/8）。缺点什么就报错，不静默省略。"""
    st = dict(spec.get("stamps") or {})
    st["source_type"] = "ai_solver"
    st["model_id"] = st.get("model_id") or spec.get("model_id") or ""
    st["uncertainty"] = uncertainty
    st["verification_level"] = verification_level or spec["state"]
    st["applicability_hit"] = bool((applicability_result or {}).get("applicable", False))
    if not st["model_id"]:
        raise SpecError("出解必须带 model_id（红线 8：AI 解要挂到具体模型版本）")
    if uncertainty in (None, "", {}, []):
        raise SpecError("出解必须带 uncertainty（红线 7：免求解器输出必须带误差界）")
    return st


def solve(spec: dict, params: dict, *, predictor=None, error_bound: Any = None) -> dict:
    """免 COMSOL 出解。**门禁顺序固定**：状态 → 适用范围 → 误差界 → 才预测。

    * 状态不是 `approved_solver` ⇒ 拒答（未放行不得出解）；
    * 参数超范围 ⇒ 拒答 + 回退 COMSOL（写明原因）；
    * 误差界缺失 ⇒ 拒答（宁可不给，也不给一个没有界的数）。
    """
    if spec["state"] != "approved_solver":
        return {"refused": True, "reason": "状态为 %s，未获放行 ⇒ 不出现场解" % spec["state"],
                "fallback": "comsol", "state": spec["state"]}
    ap = applicability(spec, params)
    if not ap["applicable"]:
        return {"refused": True, "fallback": "comsol", "applicability": ap,
                "reason": "参数超出已声明适用范围 ⇒ 拒绝出解并回退 COMSOL（§6.4 运行时规则）"}
    if error_bound in (None, "", {}, []):
        return {"refused": True, "fallback": "comsol", "applicability": ap,
                "reason": "没有场级误差界 ⇒ 拒绝出解（红线 7）"}
    if predictor is None:
        return {"refused": True, "fallback": "comsol", "applicability": ap,
                "reason": "未提供 predictor（本层只做门禁；预测由 pod.PodModel 承担）"}
    field = predictor(params)
    return {"refused": False, "field": field, "applicability": ap,
            "stamps": stamp(spec, uncertainty=error_bound, applicability_result=ap),
            "note": "本解为 ai_solver 来源，**不是** COMSOL 解；已附误差界与验证等级"}


def spec_summary(spec: dict) -> dict:
    """给界面/报告用的一页摘要（不含任何数值结果）。"""
    nxt = next_state(spec, {k: {"verdict": None} for k in ("S0", "S1", "S2", "S3", "S4", "S5")})
    return {"solver_id": spec.get("solver_id"), "state": spec.get("state"),
            "method": spec.get("method"), "model_id": spec.get("model_id"),
            "fields": spec.get("fields"), "point_set": spec.get("point_set"),
            "applicability": spec.get("applicability"),
            "thresholds": spec.get("thresholds"), "stamps": spec.get("stamps"),
            "recheck": spec.get("recheck"),
            "next_step_hint": nxt.get("reason"),
            "plan_ref": "WORKING_PLAN §6.1.1（S0–S5）/ §6.4（放行门禁）"}


def level_table(levels_out: dict) -> list[dict]:
    """把 `evaluate_levels` 的结果摊平成表（便于写进报告）。"""
    rows = []
    for name in ("S0", "S1", "S2", "S3", "S4", "S5"):
        lv = (levels_out.get("levels") or {}).get(name) or {}
        rows.append({"level": name, "verdict": lv.get("verdict", "missing"),
                     "passed": bool(lv.get("passed")),
                     "checks": lv.get("checks", [])})
    return rows
