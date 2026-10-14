# -*- coding: utf-8 -*-
"""A9「报告与增强」的**确定性写作/门禁层**（fail-closed）。

## 这一层为什么必须是代码

`AGENTS.md` 红线 1/5 与 `report-and-evidence` 技能要求：

* **没有证据就不出数字**：报告里每个数值必须挂 `run_id` / `evidence_id` / `experiment_id` /
  `feedback_id`，且这些 ID 必须在平台里**真实存在**（`trace_ids_verified` 检查，需传入已知 ID 集）；
* **没有摘录就不算文献证据**：`evidence_id` 类数值必须带原文摘录 `quote` 与页码定位 `locator`；
* **不得把待验证说成已验证**：门禁未通过时出现「已验证 / 可放行 / approved_for_use」这类措辞
  ⇒ 判失败（`no_status_upgrade`）；
* **不得只报好消息**：`not_checked` 与 `failures` 段落**必须存在且非空**；
* **无法结论时必须写清「需要补什么」**：缺口必须五要素齐全
  （缺什么 / 为什么缺 / 解锁什么 / 怎么补 / 阻塞成本）。

判定语义复用 `memsharness.consistency.evaluate_s3()`（任一 False ⇒ failed；任一 None ⇒
inconclusive 且不放行；空集合 ⇒ failed），与 A5/A8 同一套语义。

**职责边界**：本模块只做「可核验的报告骨架 + 判定」。措辞的最终质量、文献的选择、
实验的解释仍由人/A9 的 LLM 角色完成；但 `publish_allowed=False` 时，
**任何叙述都不得作为结论发布**。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .consistency import CheckResult, evaluate_s3

REPORT_VERSION = "a9-report-augment-1"

TRACE_KINDS = ("run_id", "evidence_id", "experiment_id", "feedback_id")
SOURCE_TYPES = ("simulation", "ai_solver", "analytic", "literature", "experiment", "human_feedback")

#: 结果承载段落：这些段落里出现的"测量型数字"必须能在数值主张里找到对应来源。
#: 标题也算（把结果数字写进 title 不能免检）；`limitations` 也算（适用范围里的数字同样是断言）。
RESULT_SECTIONS = ("title", "best_and_pareto", "error_bounds", "limitations")
#: **豁免**段落：它们描述的是"缺什么/不知道什么/失败什么"，其中的数字不是在报结果。
#: 豁免必须**显式声明**（见 `number_policy`），否则"漏扫"会变成隐形后门。
EXEMPT_SECTIONS = ("failures", "not_checked", "gaps", "run_index", "mixed_sources")
#: "测量型数字" = 带小数点或科学计数法（整数（如频段 20、点数 72）不在网内，见 limitations）
MEASURE_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+\.\d+(?:[eE][-+]?\d+)?|(?<![\w.])-?\d+[eE][-+]?\d+")

#: 报告必须齐备的段落（缺一段即判失败；**不得只报好消息**）
REQUIRED_SECTIONS = (
    "best_and_pareto",     # 最优 / Pareto（含口径）
    "error_bounds",        # 误差界与验证等级
    "limitations",         # 限制声明（适用范围）
    "run_index",           # run_id 索引（数字→来源）
    "not_checked",         # 没检查的项（必填、非空）
    "failures",            # 失败点与作废点（必填、非空；无失败要写「本批无失败点」并给依据）
    "gaps",                # 缺口（五要素）
)

GAP_KEYS = ("missing", "why", "unlock", "how", "cost")

GAP_KEYS = ("missing", "why", "unlock", "how", "cost")

#: **门禁未通过时**禁止出现的"结果已被验证/可用"措辞（红线 §5）。
#: ⚠️ 用**正则**而不是精确子串：A8 红队实测「已经过验证，可直接用于工程设计」这种同义改写
#: 与英文写法能原样穿过精确匹配（它当时确实穿过了）。
UPGRADE_PATTERNS_ZH = (
    r"已[^\n]{0,4}验\s*证",            # 已验证 / 已经过验证 / 已通过验证
    r"验\s*证[^\n]{0,4}通\s*过",        # 验证通过 / 验证已通过
    r"(?:可|能)(?:以)?\s*用于\s*工程\s*(?:判断|设计|决策)",
    r"(?:可|能)(?:以)?\s*直接\s*用于\s*(?:工程)?\s*设计",
    r"(?:可|能)(?:以)?\s*放心\s*使用",
    r"已\s*放行",
    r"release_allowed\s*=\s*true",
    r"(?:可|能)(?:以)?\s*用于\s*工程判断",
)
UPGRADE_PATTERNS_EN = (
    r"\bverified\b", r"\bvalidated\b", r"\bapproved\s+for\s+use\b",
    r"\bready\s+for\s+(?:design|engineering)\b", r"\breleas(?:e|ed)\b",
    r"\bsafe\s+to\s+use\b",
)
#: **模型状态非 approved_for_use 时**禁止出现的"模型已批准"措辞
MODEL_APPROVAL_PATTERNS_ZH = (
    r"模型\s*已\s*(?:经)?\s*批准", r"已\s*批准\s*使用", r"模型状态\s*已\s*升级",
    r"状态\s*升为\s*已批准", r"approved_for_use",
)
MODEL_APPROVAL_PATTERNS_EN = (r"\bmodel\s+approved\b", r"\bapproved\s+model\b")
#: 任何情况下都禁用的措辞（红线 §7：AI 解不得冒充 COMSOL 解）
ALWAYS_FORBIDDEN_ZH = (r"已验证\s*等价", r"等价\s*于\s*COMSOL", r"AI\s*解\s*等同\s*COMSOL",
                       r"与\s*COMSOL\s*等价")
ALWAYS_FORBIDDEN_EN = (r"equivalent\s+to\s+COMSOL", r"same\s+as\s+COMSOL")
#: 发射口径禁用的接收类表述（A9 契约）
RECEIVE_PATTERNS = (r"接收\s*灵敏度", r"接收\s*带宽", r"脉冲回波\s*灵敏度")


#: 否定语境前缀：`不得声称已验证` 这类**否定式表述**是诚实写法，不该被单词守卫误判。
#: 判定在**句子范围**内做（到最近的句末/换行），并且一旦出现转折词（但/然而/however）
#: 就认为否定不再管辖该命中——否则「未通过；但结果已验证」会被误放行。
NEGATION_BEFORE = ("不得", "不能", "禁止", "不要", "避免", "尚未", "未", "不", "非",
                   "not ", "no ", "never ", "without ")
SENTENCE_BOUNDARY = "。；;!！?？\n"
CONTRAST_AFTER_NEGATION = ("但", "然而", "不过", "however", "but")


def _hits(patterns: Sequence[str], text: str) -> list[str]:
    """命中并**排除否定语境**（如「不得声称已验证」）。"""
    out = []
    for p in patterns:
        flags = re.IGNORECASE if p.isascii() else 0
        for m in re.finditer(p, text, flags=flags):
            start = m.start()
            cut = max((text.rfind(ch, 0, start) for ch in SENTENCE_BOUNDARY), default=-1)
            prefix = text[cut + 1:start]
            neg_pos = max((prefix.rfind(n) for n in NEGATION_BEFORE), default=-1)
            if neg_pos >= 0:
                tail = prefix[neg_pos:]
                if not any(c in tail for c in CONTRAST_AFTER_NEGATION):
                    continue                     # 否定管辖该命中 ⇒ 不算越权措辞
            out.append(m.group(0))
            break
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class Claim:
    """一个数值主张。**没有 trace 的数字不允许进报告**。"""

    label: str
    value_text: str
    unit: str = ""
    trace_kind: str | None = None
    trace_id: str | None = None
    source_type: str | None = None
    uncertainty: str | None = None
    evidence_level: str | None = None
    quote: str | None = None
    locator: str | None = None
    derived_from: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict:
        return {"label": self.label, "value_text": self.value_text, "unit": self.unit,
                "trace_kind": self.trace_kind, "trace_id": self.trace_id,
                "source_type": self.source_type, "uncertainty": self.uncertainty,
                "evidence_level": self.evidence_level, "quote": self.quote,
                "locator": self.locator, "derived_from": list(self.derived_from),
                "note": self.note}


@dataclass
class Gap:
    """缺口：五要素齐备才可执行（技能 §5）。"""

    missing: str
    why: str
    unlock: str
    how: str
    cost: str

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in GAP_KEYS}

    def complete(self) -> bool:
        return all(str(getattr(self, k) or "").strip() for k in GAP_KEYS)


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------
def check_section_numbers_traced(doc: Mapping[str, Any],
                                 claims: Sequence[Claim]) -> CheckResult:
    """结果段落里的**测量型数字**必须能在数值主张中找到出处。

    红线的机器化：只在正文写「918.43%」而 `claims` 里没有对应条目 ⇒ 该数字没有来源。
    三处按 A8 红队反馈收紧：
    1. 扫描范围加入 `title` 与 `limitations`（原先只扫两段，标题/适用范围里的数字免检）；
    2. 出处只认 `value_text` 与 `uncertainty`——**不再把 `label` 算作出处**
       （红队实测：把数字写进 label 就能"洗白"）；
    3. 豁免段落（failures/not_checked/gaps/run_index/mixed_sources）必须在 `number_policy`
       里**显式声明**，否则判失败——把"漏扫"变成"已声明的豁免"，不再隐形。

    已知边界（写进 detail.limitations，不假装完备）：整数（20 MHz、72 个组合）仍在网外；
    本项只做字面比对，不判断数字语义是否被正确解读。
    """
    known: set[str] = set()
    for c in claims:
        for f in (c.value_text, c.uncertainty):
            known |= set(MEASURE_NUMBER_RE.findall(str(f or "")))

    def norm(x: str) -> str:
        try:
            return "%.10g" % float(x)
        except ValueError:
            return x

    known_n = {norm(x) for x in known}
    offenders: list[dict] = []
    sections = {"title": doc.get("title"), **(doc.get("sections") or {})}
    for k in RESULT_SECTIONS:
        v = sections.get(k)
        texts = [v] if isinstance(v, str) else list(v or [])
        for t in texts:
            for tok in MEASURE_NUMBER_RE.findall(str(t)):
                if norm(tok) not in known_n:
                    offenders.append({"section": k, "number": tok})
    ok = not offenders
    return CheckResult("section_numbers_traced", ok, float(len(offenders)), 0.0,
                       "" if ok else "结果段落里有 %d 处测量型数字在数值主张中找不到来源"
                                     % len(offenders),
                       {"offenders": offenders[:20],
                        "scanned_sections": list(RESULT_SECTIONS),
                        "exempt_sections": list(EXEMPT_SECTIONS),
                        "limitations": ["整数（频段/点数）与日期不在网内",
                                        "label 不再算作出处（红队：数字写进 label 即可洗白）",
                                        "豁免段落须在 number_policy 显式声明"]})


def check_number_policy_declared(doc: Mapping[str, Any]) -> CheckResult:
    """豁免段落必须**显式声明**（否则未扫描区域会变成隐形后门）。"""
    policy = doc.get("number_policy")
    if not isinstance(policy, Mapping) or not policy:
        return CheckResult("number_policy_declared", False, None, None,
                           "缺 `number_policy`：未声明哪些段落被扫描、哪些被豁免 ⇒ 未扫描区域隐形",
                           {})
    scanned = list(policy.get("scanned_sections") or [])
    exempt = list(policy.get("exempt_sections") or [])
    reason = str(policy.get("exempt_reason") or "").strip()
    bad = []
    if sorted(scanned) != sorted(RESULT_SECTIONS):
        bad.append("scanned_sections 与实现不一致：%r" % scanned)
    if sorted(exempt) != sorted(EXEMPT_SECTIONS):
        bad.append("exempt_sections 与实现不一致：%r" % exempt)
    if not reason:
        bad.append("缺 exempt_reason")
    ok = not bad
    return CheckResult("number_policy_declared", ok, float(len(bad)), 0.0,
                       "" if ok else "；".join(bad),
                       {"policy": dict(policy)})


def check_input_nonempty(claims: Sequence[Claim], gaps: Sequence[Gap],
                         sections: Mapping[str, Any]) -> CheckResult:
    n = len(claims) + len(gaps) + len(sections)
    ok = n > 0
    return CheckResult("input_nonempty", ok, float(n), 1.0,
                       "" if ok else "报告既无数值主张、又无缺口、又无段落 ⇒ 空报告（判失败）",
                       {"n_claims": len(claims), "n_gaps": len(gaps),
                        "n_sections": len(sections)})


def check_claims_traceable(claims: Sequence[Claim],
                           known_ids: Mapping[str, Iterable[str]] | None = None
                           ) -> tuple[CheckResult, CheckResult]:
    """两个检查：格式/完整性（`claims_traceable`）与**真实性**（`trace_ids_verified`）。

    * 缺 trace 的数字 ⇒ `claims_traceable=False` 并逐条列出（阻断级缺陷）；
    * 派生量必须给 `derived_from`（写出输入值来源），否则失败；
    * 未提供 `known_ids` ⇒ 真实性**无法判定**（`trace_ids_verified=None`，不放行），
      不把"格式对"当成"平台里真的存在"。
    """
    if not claims:
        return (CheckResult("claims_traceable", None, None, None,
                            "报告不含任何数值主张 ⇒ 无法判定可溯源性（不等同通过）"),
                CheckResult("trace_ids_verified", None, None, None,
                            "无主张，无可核对 ID"))
    bad = []
    for c in claims:
        if c.trace_kind not in TRACE_KINDS or not c.trace_id:
            bad.append({"label": c.label, "why": "缺少 run_id/evidence_id/experiment_id/feedback_id",
                        "trace_kind": c.trace_kind})
            continue
        if not str(c.source_type or "").strip():
            # 红线 §4：来源永不混同 ⇒ 留空就无从判断，且能"免于混源声明"（红队实测绕过）
            bad.append({"label": c.label, "why": "source_type 未声明（红线 §4：来源永不混同）"})
            continue
        if c.source_type not in SOURCE_TYPES:
            bad.append({"label": c.label, "why": "未登记的 source_type=%r" % c.source_type})
            continue
        if c.derived_from and c.trace_kind not in TRACE_KINDS:
            bad.append({"label": c.label, "why": "派生量来源非法"})
    ok = not bad
    traceable = CheckResult("claims_traceable", ok, float(len(bad)), 0.0,
                            "" if ok else "%d/%d 个数值无法溯源（阻断级缺陷）"
                                          % (len(bad), len(claims)),
                            {"n_claims": len(claims), "untraceable": bad})

    if known_ids is None:
        verified = CheckResult("trace_ids_verified", None, None, None,
                               "未提供已知 ID 集 ⇒ 只能核对格式，**不能**确认 ID 在平台中存在")
    else:
        kinds = {k: {str(x) for x in v} for k, v in known_ids.items()}
        unknown = []
        for c in claims:
            if c.trace_kind in TRACE_KINDS and c.trace_id:
                pool = kinds.get(c.trace_kind, set())
                if c.trace_id not in pool:
                    unknown.append({"label": c.label, "trace_kind": c.trace_kind,
                                    "trace_id": c.trace_id})
            for d in c.derived_from:
                if d not in {x for v in kinds.values() for x in v}:
                    unknown.append({"label": c.label, "trace_kind": "derived_from", "trace_id": d})
        ok2 = not unknown
        verified = CheckResult("trace_ids_verified", ok2, float(len(unknown)), 0.0,
                               "" if ok2 else "%d 个溯源 ID 不在平台已知 ID 集中（疑似编造/失效）"
                                             % len(unknown),
                               {"n_known": {k: len(v) for k, v in kinds.items()},
                                "unknown": unknown[:20]})
    return traceable, verified


def check_literature_quote(claims: Sequence[Claim]) -> CheckResult:
    """文献数值必须带原文摘录 + 页码定位（没有摘录就不算证据）。

    无文献类数值 ⇒ **空集上的全称命题为真**（`applicable=False`），不判为"无法判定"：
    否则任何不含文献的报告都会被卡成 inconclusive，那会让门禁失去区分力。
    """
    lit = [c for c in claims if c.trace_kind == "evidence_id" or c.source_type == "literature"]
    if not lit:
        return CheckResult("literature_quote_present", True, 0.0, 0.0, "",
                           {"applicable": False, "n_literature": 0})
    bad = [{"label": c.label, "why": "缺原文摘录 quote" if not (c.quote or "").strip()
            else ("缺页码/公式定位 locator" if not (c.locator or "").strip() else "")}
           for c in lit
           if not (c.quote or "").strip() or not (c.locator or "").strip()]
    ok = not bad
    return CheckResult("literature_quote_present", ok, float(len(bad)), 0.0,
                       "" if ok else "%d/%d 条文献数值缺摘录或页码 ⇒ 不构成证据"
                                     % (len(bad), len(lit)),
                       {"n_literature": len(lit), "bad": bad})


def check_source_mixing(claims: Sequence[Claim],
                        declared: Sequence[str] | None) -> CheckResult:
    """混用来源必须**显式声明**（红线 4：来源永不混同）。"""
    missing = [c.label for c in claims if not str(c.source_type or "").strip()]
    if missing:
        return CheckResult("source_mixing_declared", False, float(len(missing)), 0.0,
                           "%d 条数值未声明 source_type ⇒ 无法判断是否混源（且可借此免于声明）"
                           % len(missing), {"claims_without_source_type": missing[:10]})
    types = sorted({c.source_type for c in claims if c.source_type})
    if len(types) <= 1:
        return CheckResult("source_mixing_declared", True, 0.0, 0.0, "",
                           {"applicable": False, "source_types": types})
    decl = sorted({str(x) for x in (declared or [])})
    ok = set(types) == set(decl)
    return CheckResult("source_mixing_declared", ok, float(len(types)), 0.0,
                       "" if ok else "混用了 %r 但未（或未完整）在 mixed_sources 声明" % types,
                       {"source_types": types, "declared": decl})


def _texts_of(sections: Mapping[str, Any]) -> list[str]:
    out = []
    for k, v in sections.items():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, (list, tuple)):
            out.extend(str(x) for x in v)
        elif isinstance(v, dict):
            out.extend(str(x) for x in v.values())
    return out


def report_corpus(doc: Mapping[str, Any]) -> str:
    """**全报告文本语料**：标题 + 段落 + 数值主张（含 label/value/note）+ 混源声明 + 缺口/失败。

    A8 红队实测：升级措辞检查只扫 `sections` ⇒ 把「等价于 COMSOL」写进 `title` 永不命中（红线 §7）。
    因此凡是"人读得到的文字"都必须进语料。数字扫描用的是另一套更窄的规则（见 number_policy）。
    """
    parts: list[str] = [str(doc.get("title") or "")]
    sec = doc.get("sections") or {}
    if isinstance(sec, Mapping):
        parts += _texts_of(sec)
    for c in doc.get("claims") or []:
        parts += [str(c.get(k) or "") for k in ("label", "value_text", "note", "quote", "locator")]
    for g in doc.get("gaps") or []:
        if isinstance(g, Mapping):
            parts += [str(x) for x in g.values()]
    parts += [str(x) for x in (doc.get("failures") or [])]
    parts += [str(x) for x in (doc.get("not_checked") or [])]
    parts += [str(x) for x in (doc.get("mixed_sources") or [])]
    for s in doc.get("retraining_suggestions") or []:
        if isinstance(s, Mapping):
            parts += [str(x) for x in s.values()]
    return "\n".join(parts)


def check_status_upgrade(doc: Mapping[str, Any], gate: Mapping[str, Any] | None,
                         model_state: str | None, declared_state: str | None) -> CheckResult:
    """措辞与状态守卫（扫**全报告语料**，不只 sections）：

    * **门禁未通过 / 未绑定** ⇒ 不得出现"结果已验证/可用/已放行"类措辞（中英文、含同义改写）；
    * **模型状态非 `approved_for_use`** ⇒ 不得出现"模型已批准"类措辞；
    * **任何情况**下都不得出现"等价于 COMSOL"（红线 §7）；
    * 报告不得自行把状态声明为 `approved_for_use`。

    「门禁放行」与「模型状态晋升」是两件事，按两条分别判定，避免把正常表述误判成越权。
    `gate_not_applicable_reason`：当本报告确实**没有任何 A8 裁定覆盖**时，调用方必须显式声明；
    声明了且无升级措辞 ⇒ 本项通过（而不是 inconclusive），这样"诚实声明无关"与"借无关门禁背书"
    被区分开（后者由 `gate_binding` 判失败）。
    """
    text = report_corpus(doc)
    hits_always = _hits(ALWAYS_FORBIDDEN_ZH, text) + _hits(ALWAYS_FORBIDDEN_EN, text)
    if hits_always:
        return CheckResult("no_status_upgrade", False, float(len(hits_always)), 0.0,
                           "出现绝对禁止的措辞（AI 解不得宣称等价于 COMSOL）：%r" % hits_always,
                           {"hits_always": hits_always, "hits": hits_always})

    na_reason = str(doc.get("gate_not_applicable_reason") or "").strip()
    if gate is None and model_state is None and not na_reason:
        return CheckResult("no_status_upgrade", None, None, None,
                           "未提供 A8 放行裁定、未提供模型状态、也未声明『无门禁覆盖』"
                           "⇒ 无法判定措辞是否越权升级")

    gate_ok = bool(gate and gate.get("verdict") == "passed" and gate.get("release_allowed"))
    state_ok = (model_state == "approved_for_use")
    escalated = (declared_state in ("approved_for_use", "verified", "released")
                 and not state_ok)
    hits: list[str] = []
    if not gate_ok:
        hits += _hits(UPGRADE_PATTERNS_ZH, text) + _hits(UPGRADE_PATTERNS_EN, text)
    if not state_ok:
        hits += _hits(MODEL_APPROVAL_PATTERNS_ZH, text) + _hits(MODEL_APPROVAL_PATTERNS_EN, text)
    if hits or escalated:
        return CheckResult("no_status_upgrade", False, float(len(hits) + int(escalated)), 0.0,
                           "上游未放行（gate_passed=%s, model_state=%r）却出现升级措辞 %r%s"
                           % (gate_ok, model_state, hits,
                              "；报告自行声明状态 %r" % declared_state if escalated else ""),
                           {"gate_passed": gate_ok, "model_state": model_state,
                            "declared_state": declared_state, "hits": hits,
                            "scanned": "title+sections+claims+gaps+failures+not_checked"})
    return CheckResult("no_status_upgrade", True, 0.0, 0.0, "",
                       {"gate_passed": gate_ok, "model_state": model_state,
                        "gate_not_applicable_reason": na_reason or None,
                        "note": "未出现越权升级措辞"})


def check_gate_binding(doc: Mapping[str, Any], gate: Mapping[str, Any] | None,
                       gate_source: str | None) -> CheckResult:
    """门禁必须**与报告主体有绑定**，不能借一个与本报告无关的裁定来背书。

    A8 红队实测的最高危缺陷：拿 Phase 1 场执行器冻结件的 `passed` 裁定当 gate，
    报告主题完全无关，正文写"本结果已验证、可用于工程判断"⇒ 当时得到 `passed/publish_allowed=true`。

    绑定判定（任一成立即算绑定）：
    * 报告文本里出现该裁定的 `freeze_id` / `run_id` / `target_dir`；或
    * 显式声明 `gate_binding`（说明该裁定覆盖本报告的哪一部分）；
    * 或者：`gate is None` 且给出 `gate_not_applicable_reason`（诚实声明"无门禁覆盖"）。
    三者皆无 ⇒ False（拒绝）。
    """
    if gate is None:
        na = str(doc.get("gate_not_applicable_reason") or "").strip()
        if na:
            return CheckResult("gate_binding", True, 0.0, 0.0, "",
                               {"mode": "not_applicable", "reason": na,
                                "gate_source": gate_source})
        return CheckResult("gate_binding", None, None, None,
                           "未提供 gate 且未声明 `gate_not_applicable_reason` ⇒ 无法判定"
                           "（不放行；要么给绑定好的裁定，要么显式声明无门禁覆盖）")
    ids = [str(gate.get(k)) for k in ("freeze_id", "run_id", "target_dir") if gate.get(k)]
    binding = str(doc.get("gate_binding") or "").strip()
    text = report_corpus(doc)
    mentioned = [i for i in ids if i and i in text]
    ok = bool(mentioned or binding)
    return CheckResult("gate_binding", ok, float(len(mentioned)), 1.0,
                       "" if ok else
                       "该 A8 裁定（%s）与本报告**没有任何绑定**：正文未提及 %r，也未声明 gate_binding"
                       " ⇒ 不得用它为报告背书" % (ids or "无标识字段", ids[:2]),
                       {"gate_ids": ids, "mentioned_in_report": mentioned,
                        "gate_binding": binding or None, "gate_source": gate_source,
                        "gate_verdict": gate.get("verdict")})


def check_receive_wording(doc: Mapping[str, Any],
                          claims: Sequence[Claim]) -> CheckResult:
    """不得把发射结果表述为接收灵敏度（除非有实验来源支撑）。扫全报告语料。"""
    text = report_corpus(doc)
    hits = _hits(RECEIVE_PATTERNS, text)
    if not hits:
        return CheckResult("no_receive_claim", True, 0.0, 0.0, "", {"hits": []})
    has_exp = any(c.source_type == "experiment" for c in claims)
    ok = has_exp
    return CheckResult("no_receive_claim", ok, float(len(hits)), 0.0,
                       "" if ok else "出现接收类表述 %r，但报告中没有 experiment 来源支撑" % hits,
                       {"hits": hits, "has_experiment_source": has_exp})


def check_required_sections(sections: Mapping[str, Any]) -> CheckResult:
    missing = [s for s in REQUIRED_SECTIONS if not sections.get(s)]
    ok = not missing
    return CheckResult("required_sections", ok, float(len(missing)), 0.0,
                       "" if ok else "缺少必需段落（不得只报好消息）：%r" % missing,
                       {"required": list(REQUIRED_SECTIONS), "missing": missing})


def check_gaps_five_elements(gaps: Sequence[Gap]) -> tuple[CheckResult, CheckResult]:
    if not gaps:
        # 空集上的全称命题为真；"该不该有缺口"由 gaps_present_when_needed 判定
        return (CheckResult("gaps_five_elements", True, 0.0, 0.0, "",
                            {"applicable": False, "n_gaps": 0}),
                CheckResult("gaps_present_when_needed", None, None, None, "无缺口条目"))
    bad = [{"missing": g.missing[:60],
            "absent_keys": [k for k in GAP_KEYS if not str(getattr(g, k) or "").strip()]}
           for g in gaps if not g.complete()]
    ok = not bad
    five = CheckResult("gaps_five_elements", ok, float(len(bad)), 0.0,
                       "" if ok else "%d/%d 个缺口未写全五要素（缺什么/为什么缺/解锁什么/怎么补/阻塞成本）"
                                     % (len(bad), len(gaps)),
                       {"n_gaps": len(gaps), "incomplete": bad})
    return five, CheckResult("gaps_present_when_needed", None, None, None, "由汇总阶段判定")


def evaluated_gap_presence(gate: Mapping[str, Any] | None, n_gaps: int,
                           na_reason: str | None = None) -> CheckResult:
    """门禁未通过时**必须**给出缺口（否则等于"只报好消息"）。

    `na_reason` 非空 = 报告显式声明"没有任何 A8 裁定覆盖本报告" ⇒ 本项不适用（True），
    因为不存在"上游未放行"这回事；此时该报告仍受措辞守卫约束。
    """
    gate_ok = bool(gate and gate.get("verdict") == "passed")
    if gate is None:
        if str(na_reason or "").strip():
            return CheckResult("gaps_present_when_needed", True, float(n_gaps), 0.0, "",
                               {"mode": "not_applicable", "reason": na_reason, "n_gaps": n_gaps})
        return CheckResult("gaps_present_when_needed", None, None, None,
                           "未提供 A8 放行裁定、也未声明无门禁覆盖 ⇒ 无法判定是否『需要补什么』")
    if gate_ok:
        return CheckResult("gaps_present_when_needed", True, float(n_gaps), 0.0, "",
                           {"gate_ok": True, "n_gaps": n_gaps})
    ok = n_gaps > 0
    return CheckResult("gaps_present_when_needed", ok, float(n_gaps), 1.0,
                       "" if ok else "上游未放行却没有写出任何缺口（只报好消息）",
                       {"gate_ok": False, "n_gaps": n_gaps})


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def build_report(
    *,
    title: str,
    sections: Mapping[str, Any],
    claims: Sequence[Claim],
    gaps: Sequence[Gap],
    failures: Sequence[str],
    not_checked: Sequence[str],
    gate: Mapping[str, Any] | None = None,
    model_state: str | None = None,
    declared_state: str | None = None,
    known_ids: Mapping[str, Iterable[str]] | None = None,
    mixed_sources: Sequence[str] | None = None,
    retraining_suggestions: Sequence[dict] | None = None,
    upstream: Mapping[str, Any] | None = None,
    gate_source: str | None = None,
    gate_not_applicable_reason: str | None = None,
    gate_binding: str | None = None,
) -> dict:
    """产出 `analysis_report` 判定文档（fail-closed；机器可读 + 人读层共用）。

    `gate_not_applicable_reason`：本报告**确实没有任何 A8 裁定覆盖**时的显式声明。
    给了它，`no_status_upgrade` / `gaps_present_when_needed` / `gate_binding` 就不再是
    "无法判定"，而是走"诚实声明无门禁覆盖"这条路径（仍禁止任何升级措辞）。
    """
    raw_sections = dict(sections)
    sec = dict(sections)
    sec["not_checked"] = list(not_checked)
    sec["failures"] = list(failures)
    if gaps:
        sec["gaps"] = [g.to_dict() for g in gaps]
    elif not sec.get("gaps"):
        # 上游已放行 / 或报告显式声明无门禁覆盖，且确实无需补齐 ⇒ 必须**显式写出**「无缺口」
        if gate is not None and gate.get("verdict") == "passed":
            sec["gaps"] = ["（本报告无缺口：上游 A8 门禁 verdict=passed，"
                           "且报告未给出需要补数据的结论）"]
        elif str(gate_not_applicable_reason or "").strip():
            sec["gaps"] = ["（本报告无缺口：数值全部来自已有记录，且未给出需要补数据的结论；"
                           "本报告不含冻结件结论，无 A8 裁定覆盖——见 `gate_not_applicable_reason`）"]
        else:
            sec["gaps"] = []

    doc: dict[str, Any] = {
        "kind": "analysis_report",
        "report_version": REPORT_VERSION,
        "title": title,
        "gate": dict(gate) if gate else None,
        "gate_source": gate_source,
        "gate_not_applicable_reason": (str(gate_not_applicable_reason).strip()
                                       if gate_not_applicable_reason else None),
        "gate_binding": (str(gate_binding).strip() if gate_binding else None),
        "model_state": model_state,
        "declared_state": declared_state,
        "claims": [c.to_dict() for c in claims],
        "gaps": [g.to_dict() for g in gaps],
        "sections": sec,
        "failures": list(failures),
        "not_checked": list(not_checked),
        "mixed_sources": sorted({str(x) for x in (mixed_sources or [])}),
        "source_type_counts": _counts(c.source_type for c in claims),
        "evidence_level_counts": _counts(c.evidence_level for c in claims),
        "retraining_suggestions": list(retraining_suggestions or []),
        "number_policy": {
            "scanned_sections": list(RESULT_SECTIONS),
            "exempt_sections": list(EXEMPT_SECTIONS),
            "exempt_reason": ("豁免段落描述的是『缺什么/不知道什么/失败什么』，其中的数字"
                              "不是在报结果；结果型数字写进这些段落仍会被人读到，"
                              "但机器不拦——所以此处显式声明，避免『未扫描』变成隐形后门"),
            "integer_limit": "整数（频段/点数/次数）不在测量型数字网内",
        },
        "upstream": dict(upstream or {}),
    }

    checks: list[CheckResult] = []
    checks.append(check_input_nonempty(claims, gaps, raw_sections))
    traceable, verified = check_claims_traceable(claims, known_ids=known_ids)
    checks += [traceable, verified]
    checks.append(check_literature_quote(claims))
    checks.append(check_source_mixing(claims, mixed_sources))
    checks.append(check_status_upgrade(doc, gate, model_state, declared_state))
    checks.append(check_gate_binding(doc, gate, gate_source))
    checks.append(check_receive_wording(doc, claims))
    checks.append(check_section_numbers_traced(doc, claims))
    checks.append(check_number_policy_declared(doc))
    checks.append(check_required_sections(sec))
    five, _ = check_gaps_five_elements(gaps)
    checks.append(five)
    checks.append(evaluated_gap_presence(gate, len(gaps), gate_not_applicable_reason))

    verdict = dict(evaluate_s3(checks))
    doc.update({
        "verdict": verdict["verdict"],
        "publish_allowed": bool(verdict["verdict"] == "passed"),
        "checks": verdict["checks"],
        "n_checks": verdict["n_checks"], "n_failed": verdict["n_failed"],
        "n_inconclusive": verdict["n_inconclusive"], "reason": verdict["reason"],
        "semantics": (
            "fail-closed：任一检查 False ⇒ verdict=failed；任一 None ⇒ verdict=inconclusive 且 "
            "publish_allowed=False。`publish_allowed=False` 时**任何叙述都不得作为结论发布**，"
            "但仍应输出缺口清单（五要素）与未检查项。人工放行权不可由本模块或 LLM 代为行使"
            "（红线 §5）；报告不得把 draft 描述成 verified。"
            "门禁必须**与报告主体绑定**（正文提及该裁定的 freeze_id/run_id/target_dir，或声明 "
            "`gate_binding`）；确无门禁覆盖时必须显式声明 `gate_not_applicable_reason`，"
            "不得借无关裁定背书。数值主张必须声明 `source_type`（红线 §4）。"),
    })
    return doc


def _counts(it: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in it:
        if x is None:
            continue
        k = str(x)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# 反馈闭环（append-only）
# ---------------------------------------------------------------------------
FEEDBACK_KINDS = ("human", "experiment", "literature", "review")


def ingest_feedback(records: Sequence[Mapping[str, Any]], registry_path: Path) -> dict:
    """把反馈**追加**进 JSONL 注册表。

    红线 6（历史 append-only）的机器化：
    * 缺 `feedback_id` ⇒ 拒收（无法引用的人反馈等于没有）；
    * 同一 `feedback_id` 已存在且内容不同 ⇒ **拒收**（要求新开一条并写 `supersedes`），
      绝不覆盖既有记录；
    * 内容完全相同 ⇒ `noop`（幂等）。
    """
    path = Path(registry_path)
    existing: dict[str, dict] = {}
    if path.is_file():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as exc:
                # fail-closed：注册表里出现无法解析的行 ⇒ 直接拒绝继续（不许静默跳过：
                # A8 红队漏检 #2「坏行 fail-closed」——静默跳过会让"历史被改坏"看不出来）
                raise ValueError("反馈注册表第 %d 行无法解析（%s）⇒ 拒绝继续，请人工核查 %s"
                                 % (lineno, type(exc).__name__, path))
            if not isinstance(rec, dict) or not rec.get("feedback_id"):
                raise ValueError("反馈注册表第 %d 行缺 feedback_id ⇒ 注册表已损坏，拒绝继续" % lineno)
            fid0 = str(rec["feedback_id"])
            if fid0 in existing and existing[fid0] != rec:
                raise ValueError("反馈注册表里 feedback_id=%s 出现互相矛盾的两条 ⇒ 注册表已损坏，"
                                 "拒绝继续" % fid0)
            existing[fid0] = rec
    appended, rejected, noop = [], [], []
    lines: list[str] = []
    for rec in records:
        fid = str(rec.get("feedback_id") or "")
        if not fid:
            rejected.append({"record": dict(rec), "reason": "缺 feedback_id（无法被引用）"})
            continue
        kind = str(rec.get("kind") or "")
        if kind and kind not in FEEDBACK_KINDS:
            rejected.append({"feedback_id": fid, "reason": "未登记的 kind=%r" % kind})
            continue
        if fid in existing:
            if existing[fid] == dict(rec):
                noop.append(fid)
            else:
                rejected.append({"feedback_id": fid,
                                 "reason": "同一 id 内容不同 ⇒ 拒收（append-only：请新开一条并写 supersedes）"})
            continue
        lines.append(json.dumps(dict(rec), ensure_ascii=False, sort_keys=True))
        # ⚠️ 必须**在批内**同步 existing：否则同一次调用里出现两条同 id 记录时会两条都追加，
        # 注册表里就出现"同一 feedback_id 两条互相矛盾"的记录（A8 红队实测到的真实缺陷）。
        existing[fid] = dict(rec)
        appended.append(fid)
    if lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            for ln in lines:
                fh.write(ln + "\n")
        # 落盘后**回读校验**（红队建议）：追加的 id 必须都在、且不能出现重复 id
        back = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        back_ids = [str(r["feedback_id"]) for r in back]
        missing = [i for i in appended if i not in back_ids]
        dup = sorted({i for i in back_ids if back_ids.count(i) > 1})
        if missing or dup:
            raise RuntimeError("反馈写入后回读校验失败：缺失 %r；重复 id %r" % (missing, dup))
    return {"registry": str(path), "n_records": len(records),
            "appended": appended, "rejected": rejected, "noop": noop,
            "n_lines_after": (len([x for x in path.read_text(encoding="utf-8").splitlines()
                                   if x.strip()]) if path.is_file() else 0),
            "readback_verified": True,
            "append_only": True,
            "semantics": ("只追加不覆盖；同一 feedback_id 内容冲突一律拒收（**批内也拒**），"
                          "修正通过新记录 + supersedes 表达；坏行/重复 id 一律 fail-closed；"
                          "写入后回读校验。**并发写未加锁**（单写者假设，见 not_checked）。")}


def suggest_retraining(feedback_records: Sequence[Mapping[str, Any]], *,
                       gate: Mapping[str, Any] | None = None) -> list[dict]:
    """由实验/文献/人反馈触发**再训练建议**（建议不等于执行）。"""
    out: list[dict] = []
    for rec in feedback_records:
        kind = str(rec.get("kind") or "")
        verdict = str(rec.get("verdict") or "")
        fid = rec.get("feedback_id")
        if kind == "experiment":
            out.append({"trigger": "experiment", "feedback_id": fid,
                        "suggestion": "把实验点作为独立 source_type=experiment 加入留出集，"
                                      "做 L5 对标；偏差超预测区间则触发再校准",
                        "requires": ["实验不确定度", "工况与口径对齐（驱动电压/介质/温度）"],
                        "not_automatic": "模型状态晋升仍需人工放行（红线 §5）"})
        elif kind == "literature":
            out.append({"trigger": "literature", "feedback_id": fid,
                        "suggestion": "把文献值作为 evidence 级标签（带摘录+页码）加入对照，"
                                      "多源一致后才考虑升级为训练标签",
                        "requires": ["原文摘录与页码", "单位换算假设"],
                        "not_automatic": "文献值不得与仿真值混为同一来源"})
        elif verdict in ("reject", "correction"):
            out.append({"trigger": kind or "human", "feedback_id": fid,
                        "suggestion": "按人反馈修正参数/口径，并**新开一轮**训练与排名（旧结果保留并排）",
                        "requires": ["修正后的口径定义", "受影响样本清单"],
                        "not_automatic": "不得原地覆盖既有结果（append-only）"})
    if gate is not None and gate.get("verdict") != "passed":
        out.append({"trigger": "gate", "feedback_id": None,
                    "suggestion": "上游 A8 未放行 ⇒ 优先补证据/修数据，而不是继续训练",
                    "requires": ["通过的门禁裁定"],
                    "not_automatic": "训练不能替代验证"})
    return out


# ---------------------------------------------------------------------------
# 人读层
# ---------------------------------------------------------------------------
MARK = {True: "PASS", False: "FAIL", None: "UNKNOWN"}


def render_md(doc: dict) -> str:
    g = doc.get("gate") or {}
    L = ["# %s" % doc["title"], "",
         "- 报告判定：**%s**（publish_allowed=%s）" % (doc["verdict"], doc["publish_allowed"]),
         "- 上游 A8：verdict=%s release_allowed=%s" % (g.get("verdict"), g.get("release_allowed")),
         "- 模型状态：`%s`（本模块**无权**晋升，红线 §5）" % doc.get("model_state"),
         "- 版本：%s" % doc["report_version"], ""]

    L += ["## 1. 数值与来源（每个数字都必须能回溯）", "",
          "| 数值 | 单位 | 来源 ID | 来源类型 | 证据等级 | 不确定度 |",
          "|---|---|---|---|---|---|"]
    if doc["claims"]:
        for c in doc["claims"]:
            tid = ("%s=`%s`" % (c["trace_kind"], c["trace_id"])) if c.get("trace_id") else "**缺失**"
            L.append("| %s = %s | %s | %s | %s | %s | %s |" % (
                c["label"], c["value_text"], c["unit"] or "—", tid,
                c.get("source_type") or "—", c.get("evidence_level") or "—",
                c.get("uncertainty") or "未给出"))
    else:
        L.append("| （本报告不含数值主张） | — | — | — | — | — |")

    L += ["", "## 2. 最优 / Pareto", "", str(doc["sections"].get("best_and_pareto") or "（未提供）")]
    L += ["", "## 3. 误差界与验证等级", "", str(doc["sections"].get("error_bounds") or "（未提供）")]
    L += ["", "## 4. 限制声明与适用范围", "", str(doc["sections"].get("limitations") or "（未提供）")]
    L += ["", "## 5. run_id 索引", "", str(doc["sections"].get("run_index") or "（未提供）")]

    L += ["", "## 6. 本次**没有**检查的项（不得读成「查过且通过」）", ""]
    L += ["- %s" % x for x in doc["not_checked"]] or ["- （空 —— 这本身是违约项）"]

    L += ["", "## 7. 失败点与作废点（不得只报好消息）", ""]
    L += (["- %s" % x for x in doc["failures"]] or ["- （空 —— 这本身是违约项）"])

    L += ["", "## 8. 缺口与「需要补什么」（五要素）", ""]
    if doc["gaps"]:
        for i, gp in enumerate(doc["gaps"], start=1):
            L += ["### 缺口 %d" % i, "",
                  "- **缺什么**：%s" % gp["missing"],
                  "- **为什么缺**：%s" % gp["why"],
                  "- **解锁什么结论**：%s" % gp["unlock"],
                  "- **怎么补**：%s" % gp["how"],
                  "- **阻塞成本**：%s" % gp["cost"], ""]
    else:
        L += ["（未给出缺口 —— 若上游未放行，这本身是违约项）", ""]

    if doc["retraining_suggestions"]:
        L += ["## 9. 再训练/再校准建议（建议≠执行）", "",
              "| 触发 | 建议 | 前置条件 | 不得自动执行 |", "|---|---|---|---|"]
        for s in doc["retraining_suggestions"]:
            L.append("| %s | %s | %s | %s |" % (
                s["trigger"], s["suggestion"], "; ".join(s.get("requires", [])),
                s.get("not_automatic", "")))

    L += ["", "## 10. 判定明细", "", "| 检查 | 通过 | 说明 |", "|---|---|---|"]
    for c in doc["checks"]:
        L.append("| `%s` | %s | %s |" % (c["name"], MARK[c["passed"]], (c["reason"] or "")[:90]))

    L += ["", "## 判定语义", "", "```text", doc["semantics"], "```", ""]
    if doc["mixed_sources"]:
        L += ["", "来源混用声明：%s（各来源数量见 `source_type_counts`）"
              % ", ".join("`%s`" % s for s in doc["mixed_sources"]), ""]
    return "\n".join(L) + "\n"
