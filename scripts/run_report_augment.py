# -*- coding: utf-8 -*-
"""A9「报告与增强」的命令行入口：把产物写成**每个数字都能回溯**的报告 + 反馈入库。

用法：

    python scripts/run_report_augment.py ^
      --bundle work/runs/a5a9-20260916/bundle_input.json ^
      --gate work/runs/a8-gate-20260916/verdicts.json ^
      --known-ids work/runs/a5a9-20260916/known_ids.json ^
      --feedback work/runs/a5a9-20260916/feedback_new.json ^
      --feedback-registry work/runs/a5a9-20260916/feedback_registry.jsonl ^
      --out-dir work/runs/a5a9-20260916/report

`bundle_input.json` 结构（全部字段显式，避免"凭印象补数字"）：

```json
{
  "title": "…",
  "model_state": "draft",
  "declared_state": null,
  "mixed_sources": ["simulation", "literature"],
  "sections": {"best_and_pareto": "…", "error_bounds": "…",
               "limitations": "…", "run_index": "…"},
  "claims": [{"label": "...", "value_text": "...", "unit": "...",
              "trace_kind": "run_id", "trace_id": "run-...",
              "source_type": "simulation", "evidence_level": "L4",
              "uncertainty": "±3%"}],
  "gaps": [{"missing": "...", "why": "...", "unlock": "...", "how": "...", "cost": "..."}],
  "failures": ["…"], "not_checked": ["…"]
}
```

退出码：
    0 = verdict=passed（publish_allowed=True，可发布）
    2 = failed（有数字无法回溯 / 越权升级措辞 / 缺必需段落 / 缺口不完整）
    3 = inconclusive（**不得作为结论发布**）
    4 = 用法错误 / 文件缺失
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.report_augment import (  # noqa: E402
    Claim, Gap, build_report, ingest_feedback, render_md, sha256_file,
    suggest_retraining,
)


def load_gate(path: Path | None) -> dict | None:
    if path is None:
        return None
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, dict) and doc.get("kind") == "verification_verdict_set":
        vs = doc.get("verdicts") or []
        return vs[0] if vs else None
    return doc


def load_known_ids(path: Path | None) -> tuple[dict | None, dict]:
    """已知 ID 集：既接受 `{"run_id": [...]}`，也接受 `dump_known_ids.py` 的完整导出。

    返回 (id 集, 溯源信息)。**溯源信息必须随报告落盘**（A8 红队：known_ids 未哈希、未绑定，
    调用方可以塞一份被篡改的集合）。返回空集视为"没给"（不能拿空集当"全部不存在"）。
    """
    if path is None:
        return None, {}
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    ids = doc.get("ids") if isinstance(doc, dict) and isinstance(doc.get("ids"), dict) else doc
    prov = {"known_ids_source": str(p), "known_ids_sha256": sha256_file(p),
            "n_by_kind": {k: len(list(v)) for k, v in (ids or {}).items()}}
    if not ids:
        return None, prov
    return ids, prov


def claims_from(items) -> list[Claim]:
    out = []
    for it in items or []:
        kw = {k: v for k, v in it.items() if k in Claim.__dataclass_fields__}
        if isinstance(kw.get("derived_from"), list):
            kw["derived_from"] = tuple(kw["derived_from"])
        out.append(Claim(**kw))
    return out


def gaps_from(items) -> list[Gap]:
    out = []
    for it in items or []:
        missing_keys = [k for k in ("missing", "why", "unlock", "how", "cost") if k not in it]
        if missing_keys:
            raise SystemExit("缺口条目缺键 %r（五要素必须齐备）：%r" % (missing_keys, it))
        out.append(Gap(**{k: it[k] for k in ("missing", "why", "unlock", "how", "cost")}))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A9 报告与增强（可溯源报告 + 反馈闭环）")
    ap.add_argument("--bundle", required=True, help="报告输入 JSON")
    ap.add_argument("--gate", default=None, help="A8 门禁裁定 JSON（verification_verdict 或其集合）")
    ap.add_argument("--gate-not-applicable-reason", default=None,
                    help="本报告确无任何 A8 裁定覆盖时的显式声明（不得借无关裁定背书）")
    ap.add_argument("--known-ids", default=None,
                    help='已知 ID 集 JSON：{"run_id": [...], "evidence_id": [...]}')
    ap.add_argument("--feedback", default=None, help="新增反馈 JSON（列表）")
    ap.add_argument("--feedback-registry", default=None, help="反馈注册表 JSONL（append-only）")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)

    bp = Path(args.bundle)
    if not bp.is_file():
        print("找不到 bundle：%s" % bp, file=sys.stderr)
        return 4
    spec = json.loads(bp.read_text(encoding="utf-8"))
    gate_path = Path(args.gate) if args.gate else None
    gate = load_gate(gate_path)
    known, known_prov = load_known_ids(Path(args.known_ids) if args.known_ids else None)
    if args.known_ids and known is None:
        print("known-ids 为空或无法解析：%s" % args.known_ids, file=sys.stderr)
        return 4
    if args.gate and not gate_path.is_file():
        print("找不到 gate：%s" % gate_path, file=sys.stderr)
        return 4

    feedback_records = []
    if args.feedback:
        fp = Path(args.feedback)
        if not fp.is_file():
            print("找不到 feedback：%s" % fp, file=sys.stderr)
            return 4
        feedback_records = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(feedback_records, dict):
            feedback_records = [feedback_records]

    claims = claims_from(spec.get("claims"))
    gaps = gaps_from(spec.get("gaps"))
    doc = build_report(
        title=spec.get("title") or "（未命名报告）",
        sections=spec.get("sections") or {},
        claims=claims, gaps=gaps,
        failures=spec.get("failures") or [],
        not_checked=spec.get("not_checked") or [],
        gate=gate, model_state=spec.get("model_state"),
        declared_state=spec.get("declared_state"),
        known_ids=known, mixed_sources=spec.get("mixed_sources"),
        retraining_suggestions=suggest_retraining(feedback_records, gate=gate),
        gate_source=(str(gate_path) if gate_path else None),
        gate_not_applicable_reason=(spec.get("gate_not_applicable_reason")
                                    or args.gate_not_applicable_reason),
        gate_binding=spec.get("gate_binding"),
        upstream={"bundle": str(bp), "bundle_sha256": sha256_file(bp),
                  "gate_source": (str(gate_path) if gate_path else None),
                  "gate_sha256": (sha256_file(gate_path) if gate_path and gate_path.is_file()
                                  else None),
                  **known_prov},
    )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis_report.md").write_text(render_md(doc), encoding="utf-8")
    (out / "report_bundle.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    if feedback_records and args.feedback_registry:
        res = ingest_feedback(feedback_records, Path(args.feedback_registry))
        (out / "feedback_ingest.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("feedback: 追加 %d 条 / 拒收 %d 条 / 幂等 %d 条"
              % (len(res["appended"]), len(res["rejected"]), len(res["noop"])))
        for r in res["rejected"]:
            print("  拒收：%s" % r)

    print("verdict=%s publish_allowed=%s" % (doc["verdict"], doc["publish_allowed"]))
    for c in doc["checks"]:
        if c["passed"] is not True:
            print("  [%s] %s：%s" % ({False: "FAIL", None: "UNKNOWN"}[c["passed"]],
                                     c["name"], (c["reason"] or "")[:110]))
    print("md  :", out / "analysis_report.md")

    if doc["verdict"] == "failed":
        return 2
    if doc["verdict"] != "passed":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
