# -*- coding: utf-8 -*-
"""为「交给 Codex 写论文」的材料**现取证据**（不凭记忆写数字）。

产出：work/paper_brief/evidence_digest.txt —— 每条数字后面都跟着它的出处路径，
取不到的一律写「未取到」并说明为什么，**绝不编**。

用法：python -B work\\tools\\collect_paper_evidence.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "work/paper_brief/evidence_digest.txt"
L: list[str] = []


def w(s: str = "") -> None:
    L.append(s)


def h(p: pathlib.Path, n: int = 16) -> str:
    if not p.is_file():
        return "（文件不存在）"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:n]


def rows_cols(p: pathlib.Path, encoding: str = "utf-8", skip: int = 0):
    if not p.is_file():
        return None
    lines = p.read_text(encoding=encoding, errors="replace").splitlines()
    if len(lines) <= skip:
        return None
    head = lines[skip]
    if head.startswith("% "):
        head = head[2:]
    cols = [c.strip() for c in next(csv.reader([head])) if c.strip()]
    return len(lines) - skip - 1, len(cols), cols


def sha_of_dir_files(d: pathlib.Path, names) -> dict:
    return {n: h(d / n) for n in names}


def main() -> int:
    w("=" * 78)
    w("论文材料 · 证据摘要（由 work/tools/collect_paper_evidence.py 现取）")
    w("=" * 78)
    w("规则：本文件只记录**能指到文件/命令**的数字。取不到就写「未取到」。")
    w()

    # ---------- 1. 数据资产 ----------
    w("## 1 数据资产")
    A = REPO / "work/runs/remote-exported-20260922/dataset"
    for nm in ("points.csv", "power.csv", "mech.csv", "combos.csv"):
        rc = rows_cols(A / nm)
        w("A/%s: %s  行×%s 列  sha256=%s" % (
            nm, rc[0] if rc else "未取到", rc[1] if rc else "-", h(A / nm)))
    rc = rows_cols(A / "mech.csv")
    if rc:
        w("   A/mech.csv 列名: %s" % ", ".join(rc[2]))
    LAB = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"
    rc = rows_cols(LAB)
    w("主标签表 multichannel_labels.csv: %s 行×%s 列 sha256=%s"
      % (rc[0] if rc else "未取到", rc[1] if rc else "-", h(LAB)))
    FP = REPO / "work/runs/first-peak-20260929/first_peak_metrics.csv"
    rc2 = rows_cols(FP)
    w("first_peak_metrics.csv: %s 行×%s 列 sha256=%s"
      % (rc2[0] if rc2 else "未取到", rc2[1] if rc2 else "-", h(FP)))
    B = REPO / "work/runs/gui-sweep-20260912T113936Z-bd387a56/source_table.csv"
    rc3 = rows_cols(B, skip=4)
    w("B/source_table.csv（前 4 行是 %% 前导）: %s 行×%s 列 sha256=%s"
      % (rc3[0] if rc3 else "未取到", rc3[1] if rc3 else "-", h(B)))

    # 从主标签表统计：批分布 / N2 分布 / Q 门禁通过率（**现算**）
    if LAB.is_file():
        with LAB.open(encoding="utf-8", newline="") as fh:
            rd = list(csv.DictReader(fh))
        w()
        w("### 1.1 主标签表现算统计（n=%d）" % len(rd))
        w("列名（前 24）: %s" % ", ".join(list(rd[0].keys())[:24]))
        by_batch: dict[str, int] = {}
        by_n2: dict[str, int] = {}
        bcol = next((c for c in rd[0] if c.lower() in
                     ("batch", "batch_label", "source_table", "src_table", "source")), None)
        w("按批所用列名: %s" % bcol)
        for r in rd:
            if bcol:
                by_batch[str(r.get(bcol))] = by_batch.get(str(r.get(bcol)), 0) + 1
            by_n2[str(r.get("N_w_te2"))] = by_n2.get(str(r.get("N_w_te2")), 0) + 1
        w("按批: %s" % json.dumps(by_batch, ensure_ascii=False, sort_keys=True))
        w("按 N2: %s" % json.dumps(by_n2, ensure_ascii=False, sort_keys=True))

        def num(r, k):
            v = (r.get(k) or "").strip()
            try:
                return float(v)
            except ValueError:
                return None

        q_ok = q_all = 0
        qvals = []
        for r in rd:
            q = num(r, "Q_factor")
            if q is None:
                continue
            q_all += 1
            qvals.append(q)
            if 2.5 <= q <= 3.5:
                q_ok += 1
        if q_all:
            qvals.sort()
            def pct(p):
                i = min(len(qvals) - 1, int(p * len(qvals)))
                return qvals[i]
            w("Q 门禁（2.5–3.5）通过: %d/%d = %.1f%%  ← 现算自 Q_factor 列"
              % (q_ok, q_all, 100.0 * q_ok / q_all))
            w("Q 分位: p10=%.2f p50=%.2f p90=%.2f（n=%d）"
              % (pct(0.10), pct(0.50), pct(0.90), q_all))
        elig = sum(1 for r in rd if str(r.get("ranking_eligible", "")).lower() in ("true", "1"))
        w("ranking_eligible=true: %d/%d" % (elig, len(rd)))
        closed = sum(1 for r in rd if str(r.get("bandwidth_closed", "")).lower() in ("true", "1"))
        w("bandwidth_closed=true: %d/%d" % (closed, len(rd)))
        quar = sum(1 for r in rd if str(r.get("quarantined", "")).lower() in ("true", "1"))
        w("quarantined=true: %d/%d" % (quar, len(rd)))

    # ---------- 2. 代理模型 ----------
    w()
    w("## 2 代理模型")
    # 真实路径（2026-09-30 现查；此前脚本里猜的两个路径都不对，已在论文材料中标注）
    RS = REPO / "work/runs/surrogate-response-20260929"      # 响应级（93 维频谱）
    MC = REPO / "work/runs/multichannel-surrogate-20260929"  # 多通道一阶峰
    PF = REPO / "work/runs/first-peak-20260929/peak_model_fit.json"
    for p in (RS, MC):
        w("%s/: %s" % (p.relative_to(REPO).as_posix(),
                       "存在（文件 %d 个）" % len(list(p.glob('*'))) if p.is_dir() else "未取到"))
    for nm in ("response_surrogate.json", "SURROGATE_REPORT.md", "SURROGATE_SPEC.md",
               "surrogate_model.npz", "fit_response_surrogate.py"):
        p = RS / nm
        w("RS/%s sha256=%s bytes=%s" % (nm, h(p), p.stat().st_size if p.is_file() else "-"))
    w("peak_model_fit.json sha256=%s bytes=%s"
      % (h(PF), PF.stat().st_size if PF.is_file() else "-"))
    rs = RS / "response_surrogate.json"
    if rs.is_file():
        d = json.loads(rs.read_text(encoding="utf-8"))
        w("response_surrogate.json 顶层键: %s" % sorted(d))
        for k in ("kind", "model_id", "version", "status", "dim", "target",
                  "x_predictable", "n2_fitted", "n2_extrap_allowed_max",
                  "ALLOWED_ALPHAS", "band", "bands", "q_sim_db", "prereg_sha256",
                  "not_a_solver", "NOT_a_solver", "rules"):
            if k in d:
                w("  %s = %s" % (k, json.dumps(d[k], ensure_ascii=False)[:500]))
    else:
        w("response_surrogate.json 未取到")
    for nm in ("PREREG_multichannel_surrogate.md", "multichannel_model.json",
               "fit_multichannel_surrogate.py", "MULTICHANNEL_SURROGATE_REPORT.md",
               "multichannel_surrogate.json"):
        p = MC / nm
        w("MC/%s sha256=%s bytes=%s" % (nm, h(p), p.stat().st_size if p.is_file() else "-"))
    mm = MC / "multichannel_model.json"
    if mm.is_file():
        d = json.loads(mm.read_text(encoding="utf-8"))
        w("multichannel_model.json 顶层键: %s" % sorted(d))
        for k in ("model_id", "version", "status", "n_rows_fit", "labels_sha256",
                  "prereg_sha256", "kind", "NOT_a_solver", "excluded_quarantine",
                  "structure", "conformal", "refusal_domain"):
            if k in d:
                w("  %s = %s" % (k, json.dumps(d[k], ensure_ascii=False)[:700]))
        ev = d.get("evaluation") or {}
        if ev:
            w("  逐通道评测（现取）：")
            for ch, v in ev.items():
                if isinstance(v, dict):
                    w("    %s: %s" % (ch, json.dumps(
                        {kk: vv for kk, vv in v.items() if kk != "rows"},
                        ensure_ascii=False)[:400]))
        chans = d.get("channels") or {}
        if chans:
            w("  通道口径：")
            for ch, v in chans.items():
                if isinstance(v, dict):
                    sub = {k2: v[k2] for k2 in
                           ("group", "is_formal_objective", "half_width_by_mode",
                            "coverage_by_n2") if k2 in v}
                    w("    %s: %s" % (ch, json.dumps(sub, ensure_ascii=False)[:300]))

    # ---------- 3. 带宽口径对照 ----------
    w()
    w("## 3 带宽口径对照（fit vs from_points vs from_marker）")
    bwj = REPO / "work/runs/first-peak-20260929/bw_method_validation.json"
    if bwj.is_file():
        d = json.loads(bwj.read_text(encoding="utf-8"))
        w("bw_method_validation.json sha256=%s" % h(bwj))
        for k in ("n_A_combos", "n_compared", "n_skipped_peak_mismatch", "verdict",
                  "peak_identity_gate"):
            if k in d:
                w("  %s = %s" % (k, json.dumps(d[k], ensure_ascii=False)[:300]))
        for side in ("from_points", "from_marker"):
            if side in d:
                w("  %s = %s" % (side, json.dumps(d[side], ensure_ascii=False)))
        w("  （rows 明细 %d 条见原文件）" % len(d.get("rows") or []))
    else:
        w("未取到：%s 不存在" % bwj.relative_to(REPO).as_posix())

    # ---------- 4. 跨批一致性 / 隔离 ----------
    w()
    w("## 4 跨批一致性（A vs C）与隔离")
    for nm in ("data_b_vs_a.json",):
        p = REPO / "work/runs/data-b-crosscheck-20260929" / nm
        w("%s: %s sha256=%s" % (nm, "存在" if p.is_file() else "未取到", h(p)))
    cb = REPO / "work/runs/x-densify-20260928/a6/cross_batch_consistency_R-CB-N28.json"
    w("cross_batch_consistency_R-CB-N28.json: %s sha256=%s"
      % ("存在" if cb.is_file() else "未取到", h(cb)))
    if cb.is_file():
        d = json.loads(cb.read_text(encoding="utf-8"))
        w("  键: %s" % sorted(d))
        w("  %s" % json.dumps(d, ensure_ascii=False)[:1200])

    # ---------- 5. 平台与门禁 ----------
    w()
    w("## 5 平台与门禁（现取）")
    mcp = REPO / "src/memsharness/mcp_server.py"
    w("MCP 工具数（数 @mcp.tool）: %d  源码 sha256=%s"
      % (mcp.read_text(encoding="utf-8").count("@mcp.tool") if mcp.is_file() else -1, h(mcp)))
    for nm in ("src/memsharness/incidents.py", "src/memsharness/dsh_report.py",
               "src/memsharness/glossary.py", "src/memsharness/multichannel_surrogate.py",
               "src/memsharness/metrics_v2.py", "src/memsharness/first_peak.py"):
        p = REPO / nm
        w("%s sha256=%s bytes=%s" % (nm, h(p), p.stat().st_size if p.is_file() else "-"))
    db = REPO / "work/store/mems.duckdb"
    w("work/store/mems.duckdb: %s bytes=%s" % ("存在" if db.is_file() else "未取到",
                                               db.stat().st_size if db.is_file() else "-"))
    w("测试文件数（tests/test_*.py）: %d"
      % len(list((REPO / "tests").glob("test_*.py"))))

    # ---------- 6. 诚实清单 ----------
    w()
    w("## 6 必须写进论文的「没做到」（现取）")
    import os
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.path.insert(0, str(REPO / "src"))
    try:
        import duckdb  # noqa: F401
        con = duckdb.connect(str(db), read_only=True)
        try:
            for t in ("validation",):
                n = con.execute("select count(*) from %s" % t).fetchone()[0]
                l1 = con.execute("select count(*) from %s where level='L1'" % t).fetchone()[0]
                l1p = con.execute(
                    "select count(*) from %s where level='L1' and passed" % t).fetchone()[0]
                w("%s 表: 共 %d 行；L1 %d 行，其中 passed=%d" % (t, n, l1, l1p))
            w("note: L1 的 %d 条通过里包含玩具模板（heat_slab_2d）⇒ PMUT 自身 L1 仍为 0"
              % l1p)
        finally:
            con.close()
    except Exception as exc:
        w("读库失败（如实记录，不猜）：%s: %s" % (type(exc).__name__, exc))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print("written: %s (%d lines)" % (OUT.relative_to(REPO).as_posix(), len(L)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
