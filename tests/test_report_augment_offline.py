# -*- coding: utf-8 -*-
"""A9 报告与增强层的**离线自测**（pytest 风格；同时保留直接运行入口）。

对应关系（每条都来自红线或 `report-and-evidence` 技能）：
* 全链可溯源 + 门禁通过 + 模型 approved ⇒ `passed` 且 `publish_allowed=True`；
* 缺 trace 的数字 ⇒ `failed`（阻断级缺陷），**不写数字比写没来源的数字安全**；
* trace ID 不在平台已知 ID 集 ⇒ `failed`（疑似编造/失效）；
* 未提供已知 ID 集 ⇒ `trace_ids_verified=None` ⇒ `inconclusive`（格式对 ≠ 真的存在）；
* 文献数值缺 quote/locator ⇒ `failed`；
* 门禁未通过却写「已验证」⇒ `failed`；写「等价于 COMSOL」任何情况都 `failed`；
* 缺必需段落 / `not_checked` 为空 / 失败点为空 ⇒ `failed`（不得只报好消息）；
* 缺口五要素不齐 ⇒ `failed`；门禁未通过却没写缺口 ⇒ `failed`；
* 反馈入库 append-only：同 id 冲突一律拒收；幂等重复记 `noop`。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.report_augment import (  # noqa: E402
    EXEMPT_SECTIONS, Claim, Gap, build_report, ingest_feedback, render_md,
    suggest_retraining,
)

RUN_ID = "run-20260911T013401Z-7708b95e"
KNOWN = {"run_id": [RUN_ID], "feedback_id": ["fb-1"], "evidence_id": ["EV-1"]}
GATE_PASS = {"kind": "verification_verdict", "verdict": "passed", "release_allowed": True,
             "freeze_id": "freeze-x"}
GATE_FAIL = {"kind": "verification_verdict", "verdict": "failed", "release_allowed": False,
             "freeze_id": "freeze-x"}


def good_sections(**over) -> dict:
    # 默认段落**不含测量型数字**：结果段落里的数字必须由数值主张承载（见下方专门用例）
    s = {"best_and_pareto": "Pareto 前沿由 A5 产物给出；本报告只引用数值表中的值",
         "error_bounds": "误差界与验证等级见数值表（本报告不另算数字）",
         "limitations": "仅限本批参数区间与既有几何族，不得外推到阵列性能",
         "run_index": "run_index: " + RUN_ID}
    s.update(over)
    return s


def good_claim(**over) -> Claim:
    kw = dict(label="Ptot_peak", value_text="2.848e-5", unit="W", trace_kind="run_id",
              trace_id=RUN_ID, source_type="simulation", uncertainty="±5%",
              evidence_level="L4")
    kw.update(over)
    return Claim(**kw)


def good_gap() -> Gap:
    return Gap(missing="N1=6,7,8 的密频扫描", why="sweep 只到稀疏 7 点，峰值只是下界",
               unlock="把 Ptot 峰值从下界升级为可判定值", how="每点 1 次 comsolbatch 密频求解",
               cost="27 次求解（单实例串行）")


def make(**over) -> dict:
    kw = dict(title="A5/A8 结论报告", sections=good_sections(), claims=[good_claim()],
              gaps=[good_gap()], failures=["(0.65,7) 在 order=31 被距离门禁排除"],
              not_checked=["未做 COMSOL 复算", "未做实验对标"],
              gate=GATE_PASS, model_state="draft", known_ids=KNOWN,
              gate_source="work/runs/a8-gate-20260916/verdicts.json",
              gate_binding="freeze-x 覆盖本报告引用的冻结件产物")
    kw.update(over)
    return build_report(**kw)


def _get(doc: dict, name: str) -> dict:
    return next(c for c in doc["checks"] if c["name"] == name)


# ---------------------------------------------------------------------------
# 通过路径
# ---------------------------------------------------------------------------
def test_fully_traceable_report_passes_but_never_upgrades_model_state():
    doc = make()
    assert doc["verdict"] == "passed" and doc["publish_allowed"] is True
    assert doc["model_state"] == "draft"          # 报告不得自行晋升
    assert doc["source_type_counts"] == {"simulation": 1}
    assert doc["not_checked"] and doc["failures"]


def test_report_needs_no_gaps_only_if_gate_passed():
    doc = make(gaps=[])
    assert doc["verdict"] == "passed" and doc["sections"]["gaps"]
    doc2 = make(gate=GATE_FAIL, gaps=[])
    assert doc2["verdict"] == "failed"
    assert _get(doc2, "gaps_present_when_needed")["passed"] is False


# ---------------------------------------------------------------------------
# 溯源负向
# ---------------------------------------------------------------------------
def test_claim_without_trace_fails():
    doc = make(claims=[Claim("Ptot", "2.8e-5", "W")])
    assert _get(doc, "claims_traceable")["passed"] is False
    assert doc["verdict"] == "failed"
    assert _get(doc, "claims_traceable")["detail"]["untraceable"][0]["label"] == "Ptot"


def test_unknown_trace_id_fails():
    doc = make(claims=[good_claim(trace_id="run-编造的不存在的ID")])
    assert _get(doc, "trace_ids_verified")["passed"] is False
    assert doc["verdict"] == "failed"


def test_without_known_ids_truthfulness_is_inconclusive():
    doc = make(known_ids=None)
    assert _get(doc, "trace_ids_verified")["passed"] is None
    assert doc["verdict"] == "inconclusive" and doc["publish_allowed"] is False


def test_no_claims_at_all_is_inconclusive_not_pass():
    doc = make(claims=[])
    assert _get(doc, "claims_traceable")["passed"] is None
    assert doc["verdict"] == "inconclusive" and doc["publish_allowed"] is False


def test_derived_quantity_must_name_its_inputs():
    doc = make(claims=[good_claim(label="比值", value_text="1.3",
                                  derived_from=("run-不存在",))])
    assert _get(doc, "trace_ids_verified")["passed"] is False


def test_literature_claim_requires_quote_and_locator():
    lit = good_claim(trace_kind="evidence_id", trace_id="EV-1", source_type="literature",
                     quote=None, locator=None)
    doc = make(claims=[lit], known_ids={"evidence_id": ["EV-1"]})
    assert _get(doc, "literature_quote_present")["passed"] is False
    assert doc["verdict"] == "failed"
    ok = good_claim(trace_kind="evidence_id", trace_id="EV-1", source_type="literature",
                    quote="d31 = -190 pm/V", locator="p.12, Table II")
    doc2 = make(claims=[ok], known_ids={"evidence_id": ["EV-1"]})
    assert _get(doc2, "literature_quote_present")["passed"] is True


def test_mixed_sources_must_be_declared():
    claims = [good_claim(), good_claim(label="d31", value_text="-190", trace_kind="evidence_id",
                                       trace_id="EV-1", source_type="literature",
                                       quote="q", locator="p.1")]
    doc = make(claims=claims, known_ids=KNOWN)
    assert _get(doc, "source_mixing_declared")["passed"] is False
    doc2 = make(claims=claims, known_ids=KNOWN, mixed_sources=["simulation", "literature"])
    assert _get(doc2, "source_mixing_declared")["passed"] is True


# ---------------------------------------------------------------------------
# 措辞负向
# ---------------------------------------------------------------------------
def test_upgrade_wording_with_failed_gate_is_blocked():
    doc = make(gate=GATE_FAIL, sections=good_sections(best_and_pareto="该组已验证，可直接用于设计"))
    assert _get(doc, "no_status_upgrade")["passed"] is False
    assert doc["verdict"] == "failed"


def test_equivalent_to_comsol_claim_is_always_blocked():
    doc = make(sections=good_sections(limitations="本 AI 解等价于 COMSOL 解"))
    assert _get(doc, "no_status_upgrade")["passed"] is False
    assert doc["verdict"] == "failed"


def test_self_declared_state_upgrade_is_blocked():
    doc = make(declared_state="approved_for_use")
    assert _get(doc, "no_status_upgrade")["passed"] is False


def test_model_approval_wording_is_blocked_while_state_is_draft():
    # 门禁通过 ≠ 模型可批准：gate passed 时仍不得声称模型已批准
    doc = make(sections=good_sections(limitations="模型已批准使用（approved_for_use）"))
    assert _get(doc, "no_status_upgrade")["passed"] is False
    assert doc["verdict"] == "failed"


def test_gate_release_wording_is_allowed_when_gate_passed():
    # 「A8 已放行该冻结件」是关于门禁的正常表述，模型仍是 draft 时不算越权
    doc = make(sections=good_sections(run_index="A8 门禁 已放行；release_allowed=true"))
    assert _get(doc, "no_status_upgrade")["passed"] is True
    assert doc["verdict"] == "passed"


def test_without_gate_or_model_state_wording_cannot_be_judged():
    doc = make(gate=None, model_state=None)
    assert _get(doc, "no_status_upgrade")["passed"] is None
    assert doc["verdict"] == "inconclusive"


def test_receive_wording_without_experiment_source_is_blocked():
    doc = make(sections=good_sections(best_and_pareto="接收灵敏度 1.85 µm/V"))
    assert _get(doc, "no_receive_claim")["passed"] is False
    assert doc["verdict"] == "failed"


def test_number_in_result_section_must_have_a_claim():
    doc = make(sections=good_sections(error_bounds="S1 全局最大相对 L2 误差 918.43%"))
    assert _get(doc, "section_numbers_traced")["passed"] is False
    assert doc["verdict"] == "failed"
    assert _get(doc, "section_numbers_traced")["detail"]["offenders"][0]["number"] == "918.43"


def test_number_in_result_section_is_ok_when_a_claim_carries_it():
    doc = make(sections=good_sections(error_bounds="峰值功率 2.848e-5 W（见数值表）"))
    assert _get(doc, "section_numbers_traced")["passed"] is True
    assert doc["verdict"] == "passed"


def test_limitations_numbers_are_result_claims_not_exempt():
    # limitations 属结果承载段落（写在这里的数字同样是断言）⇒ 必须能溯源
    doc = make(sections=good_sections(limitations="适用于 x_scale 从 0.40 到 0.80"))
    assert _get(doc, "section_numbers_traced")["passed"] is False


# ---------------------------------------------------------------------------
# 段落 / 缺口负向
# ---------------------------------------------------------------------------
def test_missing_required_section_fails():
    s = good_sections()
    s.pop("error_bounds")
    doc = make(sections=s)
    assert _get(doc, "required_sections")["passed"] is False
    assert doc["verdict"] == "failed"


def test_empty_not_checked_or_failures_fails():
    doc = make(not_checked=[])
    assert _get(doc, "required_sections")["passed"] is False
    doc2 = make(failures=[])
    assert _get(doc2, "required_sections")["passed"] is False


def test_incomplete_gap_is_not_executable():
    bad = Gap(missing="密频扫描", why="", unlock="", how="", cost="")
    doc = make(gaps=[bad])
    assert _get(doc, "gaps_five_elements")["passed"] is False
    assert doc["verdict"] == "failed"
    assert _get(doc, "gaps_five_elements")["detail"]["incomplete"][0]["absent_keys"] == \
        ["why", "unlock", "how", "cost"]


def test_empty_report_fails():
    doc = build_report(title="空", sections={}, claims=[], gaps=[], failures=[],
                       not_checked=[], gate=None)
    assert _get(doc, "input_nonempty")["passed"] is False
    assert doc["verdict"] == "failed" and doc["publish_allowed"] is False


# ---------------------------------------------------------------------------
# 反馈闭环
# ---------------------------------------------------------------------------
def test_feedback_registry_is_append_only(tmp_path: Path):
    reg = tmp_path / "fb.jsonl"
    rec = {"feedback_id": "fb-1", "kind": "experiment", "verdict": "accept",
           "correction": "实测 20 MHz 声压 4.5e4 Pa", "reason": "实验报告 p.3"}
    r1 = ingest_feedback([rec], reg)
    assert r1["appended"] == ["fb-1"] and reg.read_text(encoding="utf-8").count("\n") == 1
    r2 = ingest_feedback([rec], reg)                       # 幂等
    assert r2["noop"] == ["fb-1"] and r2["appended"] == []
    conflict = dict(rec, correction="改成 9e4 Pa")
    r3 = ingest_feedback([conflict], reg)
    assert r3["rejected"] and "append-only" in r3["rejected"][0]["reason"]
    assert reg.read_text(encoding="utf-8").count("\n") == 1   # 原记录未被覆盖
    r4 = ingest_feedback([{"kind": "human"}], reg)
    assert r4["rejected"][0]["reason"].startswith("缺 feedback_id")


def test_retraining_suggestions_are_advisory_only():
    fb = [{"feedback_id": "fb-1", "kind": "experiment", "verdict": "accept"},
          {"feedback_id": "fb-2", "kind": "literature", "verdict": "accept"},
          {"feedback_id": "fb-3", "kind": "human", "verdict": "reject"}]
    sug = suggest_retraining(fb, gate=GATE_FAIL)
    assert {s["trigger"] for s in sug} >= {"experiment", "literature", "human", "gate"}
    assert all("not_automatic" in s for s in sug)


# ---------------------------------------------------------------------------
# 人读层
# ---------------------------------------------------------------------------
def test_render_md_lists_sources_gaps_and_not_checked():
    md = render_md(make(gate=GATE_FAIL))
    assert "每个数字都必须能回溯" in md
    assert RUN_ID in md
    assert "缺口 1" in md and "怎么补" in md
    assert "没有" in md and "失败点与作废点" in md
    assert "判定语义" in md


# ---------------------------------------------------------------------------
# A8 红队实测绕过（每条都对应一个真实被利用过的路径）
# ---------------------------------------------------------------------------
def test_unbound_foreign_gate_cannot_endorse_a_report():
    """红队最高危：借一个与报告主题无关的 passed 裁定即可拿到 publish_allowed=true。"""
    doc = make(gate_binding=None)                       # 正文也没提 freeze-x
    assert _get(doc, "gate_binding")["passed"] is False
    assert doc["verdict"] == "failed" and doc["publish_allowed"] is False
    assert "没有任何绑定" in _get(doc, "gate_binding")["reason"]
    # 正文提到该裁定的标识 ⇒ 算绑定
    ok = make(gate_binding=None,
              sections=good_sections(run_index="run_index: %s；依据 A8 裁定 freeze-x" % RUN_ID))
    assert _get(ok, "gate_binding")["passed"] is True and ok["verdict"] == "passed"


def test_no_gate_coverage_must_be_declared_explicitly():
    doc = make(gate=None, model_state="draft", gate_binding=None,
               gate_not_applicable_reason="本报告不含冻结件结论，无 A8 裁定覆盖")
    assert _get(doc, "gate_binding")["passed"] is True
    assert _get(doc, "no_status_upgrade")["passed"] is True
    assert doc["verdict"] == "passed"
    # 不声明 ⇒ 无法判定（不放行），而不是默认通过
    doc2 = make(gate=None, model_state="draft", gate_binding=None)
    assert _get(doc2, "gate_binding")["passed"] is None
    assert doc2["verdict"] == "inconclusive"


def test_forbidden_wording_in_title_is_caught():
    """红队：把「等价于 COMSOL」写进 title，原先永不命中（红线 §7）。"""
    doc = make(title="本 AI 解等价于 COMSOL")
    assert _get(doc, "no_status_upgrade")["passed"] is False
    assert doc["verdict"] == "failed"


def test_upgrade_wording_synonyms_and_english_are_caught():
    """红队：同义改写 / 英文写法曾能原样穿过精确子串匹配。"""
    for text in ("本结果已经过验证", "结果验证通过，可直接用于工程设计",
                 "This result is verified and ready for design"):
        doc = make(gate=GATE_FAIL, gate_binding=None,
                   sections=good_sections(best_and_pareto=text))
        assert _get(doc, "no_status_upgrade")["passed"] is False, text
        assert doc["verdict"] == "failed", text


def test_claim_without_source_type_is_rejected():
    """红队：source_type 留空即免于混源声明。"""
    doc = make(claims=[good_claim(source_type=None)])
    assert _get(doc, "claims_traceable")["passed"] is False
    assert _get(doc, "source_mixing_declared")["passed"] is False
    assert doc["verdict"] == "failed"


def test_number_in_title_or_limitations_is_scanned():
    doc = make(title="峰值 2.72307470962946e-05 W")
    assert _get(doc, "section_numbers_traced")["passed"] is False
    doc2 = make(sections=good_sections(limitations="适用于 x_scale 从 0.40 到 0.80"))
    assert _get(doc2, "section_numbers_traced")["passed"] is False


def test_negated_wording_is_not_flagged_but_contrast_is():
    """否定式表述（不得声称已验证）是诚实写法；但「未通过；但结果已验证」必须被抓住。"""
    ok = make(gate=GATE_FAIL, gate_binding=None,
              sections=good_sections(best_and_pareto="本报告不得把任何结论描述为已验证"))
    assert _get(ok, "no_status_upgrade")["passed"] is True
    bad = make(gate=GATE_FAIL, gate_binding=None,
               sections=good_sections(best_and_pareto="S1 未通过评估；但本次结果已验证"))
    assert _get(bad, "no_status_upgrade")["passed"] is False


def test_number_hidden_only_in_claim_label_is_not_laundered():
    """红队：把数字写进 claim.label 就能洗白（label 原先被算作出处）。"""
    c = good_claim(label="918.43", value_text="不写数字")
    doc = make(claims=[c], sections=good_sections(error_bounds="最大误差 918.43"))
    assert _get(doc, "section_numbers_traced")["passed"] is False


def test_exempt_sections_are_declared_not_silently_unscanned():
    doc = make(failures=["(0.65,7) 丢点 41.5%"])
    assert _get(doc, "number_policy_declared")["passed"] is True
    assert doc["number_policy"]["exempt_sections"] == list(EXEMPT_SECTIONS)
    assert doc["number_policy"]["exempt_reason"]


def test_ingest_feedback_fails_closed_on_corrupt_or_duplicate_history(tmp_path: Path):
    """红队漏检 #2：坏行/重复 id 必须**拒绝继续**，不能静默跳过。"""
    good = {"feedback_id": "fb-ok", "kind": "human", "verdict": "accept", "correction": "A"}
    reg = tmp_path / "fb.jsonl"
    reg.write_text(json.dumps(good, ensure_ascii=False) + "\n{坏行\n", encoding="utf-8")
    with pytest.raises(ValueError, match="无法解析"):
        ingest_feedback([dict(good, feedback_id="fb-new")], reg)
    reg2 = tmp_path / "fb2.jsonl"
    other = dict(good, correction="B")
    reg2.write_text(json.dumps(good, ensure_ascii=False) + "\n"
                    + json.dumps(other, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="互相矛盾"):
        ingest_feedback([dict(good, feedback_id="fb-new2")], reg2)
    # 正常路径：写入后回读校验并如实报告行数
    reg3 = tmp_path / "fb3.jsonl"
    res = ingest_feedback([dict(good, feedback_id="fb-x")], reg3)
    assert res["readback_verified"] is True and res["n_lines_after"] == 1


def test_ingest_feedback_rejects_duplicate_inside_one_batch(tmp_path: Path):
    """红队确认的根因：同一次调用内两条同 id 记录曾**都被追加**，
    注册表里于是出现"同一 feedback_id 两条互相矛盾记录"。"""
    reg = tmp_path / "fb.jsonl"
    a = {"feedback_id": "fb-dup", "kind": "human", "verdict": "accept", "correction": "A"}
    b = dict(a, verdict="correction", correction="B")
    res = ingest_feedback([a, b], reg)
    assert res["appended"] == ["fb-dup"] and len(res["rejected"]) == 1
    assert "append-only" in res["rejected"][0]["reason"]
    lines = reg.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["correction"] == "A"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
