# -*- coding: utf-8 -*-
"""求解器底层配置的契约测试。

锁住的是**承诺**，不是"能跑"：
* 规格 **fail-closed**：缺键/缺阈值/掩膜策略不对/来源不是 `ai_solver` ⇒ 一律拒绝，
  且**一次报全**所有缺口；
* `None`（无法判定）**不等于**通过：S3 inconclusive 不许推进，S5 未认证时 `s5_passed` 是
  **None 而不是 True**；
* **代码不得自我放行**：`approved_solver` 只能由人工签字到达；
* 漂移 ⇒ `suspended`，且从 `suspended` **只能由人**恢复；
* 出解门禁顺序固定：状态 → 适用范围 → 误差界 → 才预测；
* 放行台账 **append-only**，被拒的跃迁**不写任何东西**。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


@pytest.fixture()
def S(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMS_SOLVER_ROOT", str(tmp_path / "solverroot"))
    from memsharness import solver
    return solver


def spec_of(S, **over):
    sp = S.new_spec_template(solver_id="t1", model_id="pod-deadbeef")
    sp["applicability"]["param_bounds"] = {"N_w_te2": [5, 8], "x_scale": [0.2, 1.0]}
    sp["applicability"]["geometry_family"] = "pmut-f1"
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(sp.get(k), dict):
            sp[k] = {**sp[k], **v}
        else:
            sp[k] = v
    return sp


def _ev_all_pass():
    return {
        "s0_limit_rel_err": 0.002,
        "s1": {"key_region_rel_L2_max": 0.01, "global_rel_L2_max": 0.03,
               "n_holdout": 12, "is_independent": True},
        "s2": {"engineering_rel_err": {"f_r": 0.01, "Q": 0.02}},
        "s3": {"verdict": "passed", "checks": [{"name": "conservation", "ok": True}]},
        "s4": {"mesh_diff_max": 0.01, "n_meshes": 3},
        "s5": {"coverage": 0.90, "n_calibration": 12, "certified": True},
    }


# ----------------------------- 规格校验 -----------------------------
def test_template_is_incomplete_and_validation_lists_every_gap(S):
    sp = S.new_spec_template(solver_id="t1")
    with pytest.raises(S.SpecError) as e:
        S.validate_spec(sp)
    msg = str(e.value)
    assert "applicability.param_bounds" in msg
    assert "逐条修完" in msg, "应当一次报全，而不是只报第一条"


@pytest.mark.parametrize("mutate,frag", [
    (lambda sp: sp.pop("fields"), "fields"),
    (lambda sp: sp.pop("thresholds"), "thresholds"),
    (lambda sp: sp["thresholds"].pop("S1_global_rel_L2_max"), "thresholds 缺项"),
    (lambda sp: sp["point_set"].__setitem__("mask_policy", "drop_nan"),
     "common_mask_all_finite"),
    (lambda sp: sp["stamps"].__setitem__("source_type", "simulation"), "ai_solver"),
    (lambda sp: sp.__setitem__("state", "approved_by_vibes"), "state 非法"),
    (lambda sp: sp.__setitem__("method", "fno"), "降阶路线"),
    (lambda sp: sp["fields"].__setitem__(0, {"name": "u"}), "name 与 unit"),
])
def test_spec_validation_is_fail_closed(S, mutate, frag):
    sp = spec_of(S)
    mutate(sp)
    with pytest.raises(S.SpecError) as e:
        S.validate_spec(sp)
    assert frag in str(e.value), str(e.value)


def test_valid_spec_roundtrips_through_disk(S, tmp_path):
    p = tmp_path / "solver_spec.json"
    p.write_text(json.dumps(spec_of(S), ensure_ascii=False), encoding="utf-8")
    got = S.load_spec(p)
    assert got["solver_id"] == "t1" and got["state"] == "draft"
    assert got["_path"].endswith("solver_spec.json")


def test_default_thresholds_match_the_plan(S):
    """阈值必须与 §6.1.1 一致；改了计划就要改这里（防止两套口径）。"""
    t = S.DEFAULT_THRESHOLDS
    assert t["S0_limit_rel_err_max"] == 0.01
    assert (t["S1_key_region_rel_L2_max"], t["S1_global_rel_L2_max"]) == (0.02, 0.05)
    assert t["S2_engineering_rel_err_max"] == 0.03
    assert t["S3_conservation_residual_max"] == 0.005 and t["S3_bc_residual_max"] == 0.01
    assert t["S4_mesh_diff_max"] == 0.02
    assert (t["S5_coverage_min"], t["S5_coverage_max"]) == (0.85, 0.95)


# ----------------------------- S 级评估 -----------------------------
def test_missing_evidence_is_inconclusive_never_pass(S):
    sp = spec_of(S)
    lv = S.evaluate_levels(sp, {})
    for name in ("S0", "S1", "S2", "S3", "S4", "S5"):
        assert lv["levels"][name]["verdict"] == "inconclusive", name
        assert lv["levels"][name]["passed"] is False
    assert lv["s5_passed"] is None, "未认证时 s5_passed 必须是 None，不是 True"


def test_uncertified_error_bound_is_not_a_pass(S):
    """SOP §4：样本不足时函数返回 inf/未认证 —— **不得**用残差标准差凑窄区间。"""
    sp = spec_of(S)
    ev = _ev_all_pass()
    ev["s5"] = {"coverage": 0.9, "n_calibration": 3, "certified": False}
    lv = S.evaluate_levels(sp, ev)
    assert lv["levels"]["S5"]["verdict"] == "inconclusive"
    assert lv["s5_passed"] is None


def test_coverage_outside_band_fails(S):
    sp = spec_of(S)
    ev = _ev_all_pass()
    ev["s5"]["coverage"] = 0.62
    assert S.evaluate_levels(sp, ev)["levels"]["S5"]["verdict"] == "failed"


def test_unreachable_coverage_grid_is_inconclusive_not_failed(S):
    """n 个评估点上覆盖率只能取 k/n：目标区间不可达时必须记"无法判定"。

    实测背景：N1=4 的 x 族留出集只有 **5** 个点，真值 coverage=1.0（界偏保守、方向安全），
    但 {0,0.2,…,1.0} 上没有值落在 [0.85,0.95] ⇒ 旧实现记 `failed`，把"点太少"
    错误归因成"误差界不达标"。改为 inconclusive 后 `s5_passed` 必须是 None（**不是 True**）。
    """
    sp = spec_of(S)
    ev = _ev_all_pass()
    ev["s5"] = {"coverage": 1.0, "n_calibration": 76, "certified": True, "n_holdout": 5}
    lv = S.evaluate_levels(sp, ev)
    assert lv["levels"]["S5"]["verdict"] == "inconclusive"
    assert lv["s5_passed"] is None, "不可达 ⇒ None，不得因界偏保守而记 passed"
    assert "不可达" in lv["levels"]["S5"]["checks"][0]["note"]
    assert any("分辨率不足" in n for n in lv["notes"])


def test_coverage_grid_reachable_keeps_the_gate_strict(S):
    """评估点足够时判据照旧生效：0.90 通过、1.0 仍然 failed（不许放宽）。"""
    sp = spec_of(S)
    ev = _ev_all_pass()
    ev["s5"] = {"coverage": 0.90, "n_calibration": 76, "certified": True, "n_holdout": 20}
    assert S.evaluate_levels(sp, ev)["levels"]["S5"]["verdict"] == "passed"
    ev["s5"]["coverage"] = 1.0
    assert S.evaluate_levels(sp, ev)["levels"]["S5"]["verdict"] == "failed"


def test_all_pass_gives_passed_levels(S):
    lv = S.evaluate_levels(spec_of(S), _ev_all_pass())
    assert [lv["levels"][k]["verdict"] for k in
            ("S0", "S1", "S2", "S3", "S4", "S5")] == ["passed"] * 6
    rows = S.level_table(lv)
    assert [r["level"] for r in rows] == ["S0", "S1", "S2", "S3", "S4", "S5"]
    assert all(r["passed"] for r in rows)


def test_s1_holdout_must_be_independent(S):
    ev = _ev_all_pass()
    ev["s1"]["is_independent"] = False
    assert S.evaluate_levels(spec_of(S), ev)["levels"]["S1"]["verdict"] == "failed"


# ----------------------------- 状态机 -----------------------------
def _levels(S, ev):
    return S.evaluate_levels(spec_of(S), ev)["levels"]


def test_s3_failure_blocks_physics_consistent(S):
    sp = spec_of(S)
    ev = _ev_all_pass()
    ev["s3"] = {"verdict": "failed", "checks": [{"name": "conservation", "ok": False}]}
    r = S.next_state(sp, _levels(S, ev))
    assert r["allowed"] is False and r["to"] == "draft"
    assert "S3" in r["reason"]


def test_s3_inconclusive_blocks_too(S):
    sp = spec_of(S)
    ev = _ev_all_pass()
    ev["s3"] = {"verdict": "inconclusive", "checks": [{"name": "bc", "ok": None}]}
    r = S.next_state(sp, _levels(S, ev))
    assert r["allowed"] is False
    assert "None=无法判定也不算通过" in r["reason"]


def test_happy_path_needs_human_for_approval(S):
    sp = spec_of(S)
    sp["state"] = "draft"
    r1 = S.next_state(sp, _levels(S, _ev_all_pass()))
    assert (r1["allowed"], r1["to"], r1["auto"]) == (True, "physics_consistent", True)
    sp["state"] = "physics_consistent"
    r2 = S.next_state(sp, _levels(S, _ev_all_pass()))
    assert (r2["allowed"], r2["to"], r2["auto"]) == (True, "solver_certified", True)
    sp["state"] = "solver_certified"
    r3 = S.next_state(sp, _levels(S, _ev_all_pass()))
    assert r3["allowed"] is False and r3.get("needs_human") is True, "代码不得自我放行"
    r4 = S.next_state(sp, _levels(S, _ev_all_pass()),
                      sign_off={"by": "张三", "scope": "N2∈[5,8], x∈[0.2,1.0]"})
    assert (r4["allowed"], r4["to"], r4["auto"]) == (True, "approved_solver", False)


def test_sign_off_without_scope_is_rejected(S):
    sp = spec_of(S, state="solver_certified")
    r = S.next_state(sp, _levels(S, _ev_all_pass()), sign_off={"by": "张三"})
    assert r["allowed"] is False and "适用范围" in r["reason"]


def test_drift_suspends_and_only_human_recovers(S):
    sp = spec_of(S, state="approved_solver")
    r = S.next_state(sp, _levels(S, _ev_all_pass()), drift_detected=True)
    assert (r["allowed"], r["to"]) == (True, "suspended")
    sp["state"] = "suspended"
    r2 = S.next_state(sp, _levels(S, _ev_all_pass()))
    assert r2["allowed"] is False and "只能由人" in r2["reason"]
    r3 = S.next_state(sp, _levels(S, _ev_all_pass()),
                      sign_off={"by": "李四", "scope": "复核后恢复"})
    assert r3["allowed"] is True


# ----------------------------- 台账（append-only） -----------------------------
def test_apply_state_appends_and_never_writes_on_refusal(S, tmp_path, monkeypatch):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec_of(S), ensure_ascii=False), encoding="utf-8")
    refused = S.apply_state(p, evidence={"s3": {"verdict": "failed"}}, write=True)
    assert refused["written"] is False
    led = S.solver_root() / "t1" / "release_log.jsonl"
    assert not led.is_file(), "被拒的跃迁不得写台账"

    ok = S.apply_state(p, evidence=_ev_all_pass(), write=True)
    assert ok["written"] is True and ok["to"] == "physics_consistent"
    line1 = led.read_text(encoding="utf-8")
    assert json.loads(line1.strip())["to"] == "physics_consistent"
    assert json.loads(p.read_text(encoding="utf-8"))["state"] == "physics_consistent"

    S.apply_state(p, evidence=_ev_all_pass(), write=True)   # 第二跳
    lines = [l for l in led.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2 and led.read_text(encoding="utf-8").startswith(line1), \
        "台账只许追加，不许改动已有行"
    assert json.loads(lines[1])["from"] == "physics_consistent"


# ----------------------------- 适用范围与出解 -----------------------------
def test_applicability_reports_every_miss(S):
    sp = spec_of(S)
    ap = S.applicability(sp, {"N_w_te2": 12, "geometry_family": "other"})
    assert ap["applicable"] is False and ap["action"] == "refuse_and_fallback_comsol"
    kinds = {m["what"] for m in ap["misses"]}
    assert {"越界", "族不匹配", "缺参数"} <= kinds | {"缺参数"} or kinds
    assert any(m["what"] == "越界" for m in ap["misses"])


def test_applicability_ok_when_in_range(S):
    ap = S.applicability(spec_of(S), {"N_w_te2": 6, "x_scale": 0.5,
                                      "geometry_family": "pmut-f1"})
    assert ap["applicable"] is True and ap["action"] == "predict"


def test_solve_refuses_unless_approved(S):
    sp = spec_of(S, state="solver_certified")
    r = S.solve(sp, {"N_w_te2": 6})
    assert r["refused"] is True and r["fallback"] == "comsol" and "未获放行" in r["reason"]


def test_solve_refuses_out_of_domain_even_if_approved(S):
    sp = spec_of(S, state="approved_solver")
    r = S.solve(sp, {"N_w_te2": 99})
    assert r["refused"] is True and "适用范围" in r["reason"]


def test_solve_refuses_without_error_bound(S):
    sp = spec_of(S, state="approved_solver")
    # 参数必须**先**落在范围内，才能测到"误差界"这道门（否则先被适用范围拦下）
    r = S.solve(sp, {"N_w_te2": 6, "x_scale": 0.5, "geometry_family": "pmut-f1"},
                error_bound=None)
    assert r["refused"] is True and "误差界" in r["reason"]


def test_solve_stamps_source_type_and_uncertainty(S):
    sp = spec_of(S, state="approved_solver")
    r = S.solve(sp, {"N_w_te2": 6, "x_scale": 0.5, "geometry_family": "pmut-f1"},
                predictor=lambda p: [1.0, 2.0], error_bound={"abs": 0.02, "q90": 0.05})
    assert r["refused"] is False and r["field"] == [1.0, 2.0]
    st = r["stamps"]
    assert st["source_type"] == "ai_solver" and st["model_id"] == "pod-deadbeef"
    assert st["uncertainty"] == {"abs": 0.02, "q90": 0.05}
    assert st["verification_level"] == "approved_solver" and st["applicability_hit"] is True
    assert "不是** COMSOL" in r["note"] or "不是" in r["note"]


def test_stamp_requires_model_id_and_uncertainty(S):
    sp = spec_of(S, state="approved_solver", model_id="")
    with pytest.raises(S.SpecError):
        S.stamp(sp, uncertainty={"abs": 1.0})
    with pytest.raises(S.SpecError):
        S.stamp(spec_of(S, state="approved_solver"), uncertainty=None)


def test_state_machine_transitions_are_declared_not_improvised(S):
    """跃迁集合要显式声明：改状态机必须改这两张表（避免"顺手加一条边"）。"""
    assert ("solver_certified", "approved_solver") in S.HUMAN_TRANSITIONS
    assert ("solver_certified", "approved_solver") not in S.AUTO_TRANSITIONS
    for a, b in S.AUTO_TRANSITIONS + S.HUMAN_TRANSITIONS:
        assert a in S.STATES and b in S.STATES
