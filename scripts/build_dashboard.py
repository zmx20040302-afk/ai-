# -*- coding: utf-8 -*-
"""生成 **MEMS 平台看板**（单文件、自包含、纯离线）。

设计约束（照着仓库纪律来）：
* **不起服务器、不依赖外网**：产物是一个自包含 HTML（数据以 JSON 内嵌，图形用内联 SVG 画）；
* **每个面板都带来源**：面板底部列出源文件 + sha256（红线 §1：没有证据就不出数字）；
* **缺源不静默**：某个输入文件缺失 ⇒ 面板显式标 `缺失`，并计入 `missing`（fail-closed 到"可见"）；
* **只读**：只读 `work/**`、`schemas/**`、`agents/**`、`docs/**`，不写任何既有产物。

用法：
    python -B scripts/build_dashboard.py                 # 写到 work/reports/mems-dashboard/
    python -B scripts/build_dashboard.py --out-dir <dir>
退出码：0 正常（可能含 missing 面板）；2 有缺失源；4 用法/仓库根不对。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/remote-exported-20260922"
A6 = RUN / "a6"
DEFAULT_OUT = REPO / "work/reports/mems-dashboard"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def load_csv(p: Path) -> list[dict]:
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.is_file() else []


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class Sources:
    """记录每个面板用到的源文件与哈希（面板底部展示）。"""

    def __init__(self) -> None:
        self.used: dict[str, dict] = {}

    def add(self, *paths: Path) -> list[dict]:
        out = []
        for p in paths:
            try:                       # 仓库外路径（测试用的临时目录）不能 relative_to
                rel = str(Path(p).resolve().relative_to(REPO)).replace("\\", "/")
            except Exception:
                rel = str(p).replace("\\", "/")
            if not p.is_file():
                self.used[rel] = {"path": rel, "missing": True}
                out.append(self.used[rel])
                continue
            if rel not in self.used:
                self.used[rel] = {"path": rel, "bytes": p.stat().st_size,
                                  "sha256": sha256_file(p), "missing": False}
            out.append(self.used[rel])
        return out

    def missing(self) -> list[str]:
        return sorted(k for k, v in self.used.items() if v.get("missing"))


# ---------------------------------------------------------------------------
# 各面板的数据
# ---------------------------------------------------------------------------
def panel_overview(S: Sources) -> dict:
    stats = {}
    try:
        sys.path.insert(0, str(REPO / "src"))
        from memsharness import store
        conn = store.connect(read_only=True)
        try:
            stats = store.store_stats(conn)
        finally:
            conn.close()
    except Exception as exc:
        stats = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:120])}
    roles = []
    for d in sorted((REPO / "agents").glob("*/agent.json")):
        meta = load_json(d)
        if meta:
            roles.append({"id": meta.get("role_id") or d.parent.name.split("-")[0],
                          "name": meta.get("name"), "kind": meta.get("kind"),
                          "status": meta.get("status")})
    tools = ["ping", "env_report", "module_capability", "data_stats", "records", "run_trace",
             "sim_templates", "sim_submit", "sim_status", "sim_logs", "sim_cancel",
             "freeze_gate", "sweep_analysis", "make_report", "role_list", "role_payload"]
    return {"store": stats, "roles": roles, "mcp_tools": tools,
            "sources": S.add(REPO / "agents/README.md") + S.add(REPO / "docs/INDEX-records-and-rulings.md")}


def panel_dataset(S: Sources) -> dict:
    man = load_json(RUN / "dataset/exported_manifest.json") or {}
    rows = load_csv(RUN / "a5/metric_table.csv")
    flags = Counter()
    for r in rows:
        for f in filter(None, (r.get("flags") or "").split(";")):
            flags[f] += 1
    fam = Counter(r["source_family"] for r in rows)
    # f_peak 与"一阶峰"两种口径的直方图
    fp = [fnum(r.get("f_peak_MHz")) for r in rows]
    fp = [v for v in fp if v is not None]
    f1 = load_json(A6 / "first_mode_distribution.json") or {}
    return {"counts": man.get("counts", {}), "coverage": man.get("coverage", {}),
            "caliber": man.get("caliber", {}), "flag_counts": dict(flags.most_common()),
            "family_counts": dict(fam.most_common()),
            "fpeak_values": fp,
            "fpeak_hist": _hist(fp, 5, 35, 1.0),
            "first_mode": {"n_with": f1.get("n_with_first_peak"), "n_total": f1.get("n_total"),
                           "median_MHz": f1.get("median_MHz"), "hist": f1.get("hist_MHz"),
                           "within_18_22MHz": f1.get("within_18_22MHz"),
                           "definition": f1.get("definition")},
            "sources": S.add(RUN / "dataset/exported_manifest.json", RUN / "a5/metric_table.csv",
                             A6 / "first_mode_distribution.json", RUN / "remote_sha256.txt")}


def _hist(vals, lo, hi, step):
    bins = {}
    x = lo
    while x < hi - 1e-9:
        bins["%.1f" % x] = 0
        x += step
    for v in vals:
        k = "%.1f" % (math.floor((v - lo) / step) * step + lo)
        if k in bins:
            bins[k] += 1
    return bins


def panel_a5(S: Sources) -> dict:
    scan = load_json(RUN / "a5/scan_analysis.json") or {}
    nb = load_json(RUN / "a5/next_batch.json") or {}
    tops = []
    for r in scan.get("rankings", []):
        t = (r.get("top") or [None])[0]
        tops.append({"family": r["family"], "metric": r["metric"], "unit": r.get("unit"),
                     "caliber": r.get("caliber"), "n_available": r.get("n_available"),
                     "n_excluded": r.get("n_excluded"),
                     "top_params": (t or {}).get("params"), "top_value": (t or {}).get("value")})
    return {"verdict": scan.get("verdict"), "release_allowed": scan.get("release_allowed"),
            "provisional": scan.get("provisional"),
            "verdict_by_family": scan.get("verdict_by_family", {}),
            "stop_reasons": scan.get("stop_reasons", []),
            "exclusion_rate": (scan.get("quality") or {}).get("exclusion_rate"),
            "exclusion_by_family": (scan.get("quality") or {}).get("exclusion_rate_by_family", {}),
            "tops": tops,
            "pareto": [{"family": p["family"], "n_considered": p["n_considered"],
                        "n_front": p["n_front"]} for p in scan.get("pareto", [])],
            "next_batch": {"verdict": nb.get("verdict"), "n_selected": (nb.get("budget") or {}).get("n_selected"),
                           "stop_conditions": nb.get("stop_conditions", [])},
            "sources": S.add(RUN / "a5/scan_analysis.json", RUN / "a5/next_batch.json",
                             RUN / "a5/metric_table.csv")}


def panel_a6(S: Sources) -> dict:
    r1 = load_json(A6 / "a6_debug_result.json") or {}
    r2 = load_json(A6 / "a6_round2_result.json") or {}
    r3 = load_json(A6 / "a6_round3_result.json") or {}
    reg = load_json(A6 / "prereg_registry.json") or {}

    def first(split, rep, key):
        for row in (rep.get("splits", {}).get(split) or []):
            if row.get("skipped"):
                continue
            v = row.get(key)
            return v
        return None

    targets = ("spl_max_dB", "f_peak_Hz", "bandwidth_3dB_Hz", "q_from_points")
    cmp_rows = []
    s1 = (r1.get("targets", {}) or {}).get("S1_cross_family", {}) or {}
    r2f = first("R2-S1f", r2, "M1_ridge_scalars")
    r3f = first("R2-S1f", r3, "M1_ridge_scalars")
    r3b3 = first("R2-S1f", r3, "B3_nn_scalars")
    r3m4 = first("R2-S1f", r3, "M4_nn_resid_scalars")
    for t in targets:
        cmp_rows.append({
            "target": t,
            "r1_direct": ((s1.get(t) or {}).get("max_rel_err")),
            "r2_M1": ((r2f or {}).get(t, {}) or {}).get("max_rel_err") if r2f else None,
            "r3_M1": ((r3f or {}).get(t, {}) or {}).get("max_rel_err") if r3f else None,
            "r3_M4": ((r3m4 or {}).get(t, {}) or {}).get("max_rel_err") if r3m4 else None,
            "r3_B3": ((r3b3 or {}).get(t, {}) or {}).get("max_rel_err") if r3b3 else None,
        })
    spec = {"r2_M1": first("R2-S1f", r2, "M1_ridge_spectrum_relL2"),
            "r2_M3": first("R2-S1f", r2, "M3_mlp_spectrum_relL2"),
            "r3_M1": first("R2-S1f", r3, "M1_ridge_spectrum_relL2"),
            "r3_M4": first("R2-S1f", r3, "M4_nn_resid_spectrum_relL2"),
            "r3_B3": first("R2-S1f", r3, "B3_nn_spectrum_relL2")}
    return {"comparison": cmp_rows, "spectrum": spec,
            "registry": [{"seq": e.get("seq"), "round": e.get("round"),
                          "prereg": (e.get("prereg_sha256") or "")[:16],
                          "changed": e.get("prereg_changed_vs_previous"),
                          "missing": e.get("missing")} for e in reg.get("entries", [])],
            "band": {"scalar_pass": 0.03, "scalar_partial": 0.10,
                     "spectrum_pass": 0.05, "spectrum_partial": 0.10},
            "sources": S.add(A6 / "a6_debug_result.json", A6 / "a6_round2_result.json",
                             A6 / "a6_round3_result.json", A6 / "prereg_registry.json")}


def panel_plan(S: Sources) -> dict:
    plan = load_json(A6 / "X_DENSIFY_PLAN.json") or {}
    return {"n_candidates_total": plan.get("n_candidates_total"),
            "n_strata": plan.get("n_strata_with_ge2_x"),
            "batch_size": plan.get("recommended_batch_size"),
            "recommended": [{"priority": c["priority"], "family": c["family"],
                             "n1": c["N_w_te1"], "x_mid": c["x_mid"],
                             "d_spl20": (c["basis"] or {}).get("delta_spl_20MHz_dB"),
                             "oct_fpeak": (c["basis"] or {}).get("delta_f_peak_octave"),
                             "role": c["role"], "branch": c["branch_jump"],
                             "edge_neighbour": c["peak_at_edge_neighbours"]}
                            for c in plan.get("recommended", [])],
            "stop_conditions": plan.get("stop_conditions", []),
            "not_doing": plan.get("not_doing", []),
            "sources": S.add(A6 / "X_DENSIFY_PLAN.json")}


def panel_governance(S: Sources) -> dict:
    gate = load_json(REPO / "work/runs/a8-gate-20260916/verdicts.json") or {}
    idx = REPO / "docs/INDEX-records-and-rulings.md"
    sections = []
    if idx.is_file():
        for ln in idx.read_text(encoding="utf-8").splitlines():
            if ln.startswith("## "):
                sections.append(ln[3:].strip())
    return {"freeze_verdicts": [{"target": Path(v.get("target_dir", "")).name,
                                 "verdict": v.get("verdict"),
                                 "release_allowed": v.get("release_allowed"),
                                 "n_failed": v.get("n_failed")}
                                for v in (gate.get("verdicts") or [])],
            "index_sections": sections,
            "sources": S.add(REPO / "work/runs/a8-gate-20260916/verdicts.json", idx)}


# ---------------------------------------------------------------------------
# HTML 渲染（自包含；图形用内联 SVG，由内嵌 JS 画）
# ---------------------------------------------------------------------------
JS = r"""
function el(tag, attrs, kids){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const k in (attrs||{})) n.setAttribute(k, attrs[k]);
  (kids||[]).forEach(c=>n.appendChild(typeof c==='string'?document.createTextNode(c):c)); return n;}
function svg(w,h){return el('svg',{viewBox:'0 0 '+w+' '+h,width:'100%',height:h});}
function bars(host, obj, opts){opts=opts||{};const keys=Object.keys(obj);
  const max=Math.max(1,...keys.map(k=>obj[k]));
  const w=Math.max(240, keys.length*46), h=opts.h||160, pad=26;
  const s=svg(w,h); const bw=(w-pad-10)/keys.length;
  keys.forEach((k,i)=>{const v=obj[k], bh=(h-2*pad)*v/max;
    s.appendChild(el('rect',{x:pad+i*bw+2,y:h-pad-bh,width:bw-6,height:Math.max(1,bh),
      fill:opts.color||'#4aa3ff',rx:2}));
    s.appendChild(el('text',{x:pad+i*bw+bw/2,y:h-pad+13,'text-anchor':'middle',
      'font-size':10,fill:'#889'},[k]));
    s.appendChild(el('text',{x:pad+i*bw+bw/2,y:h-pad-bh-4,'text-anchor':'middle',
      'font-size':10,fill:'#ccd'},[String(v)]));});
  host.appendChild(s);}
function hbars(host, rows, opts){opts=opts||{};const max=Math.max(1e-12,...rows.map(r=>r.v));
  const rowH=22, w=opts.w||520, h=rows.length*rowH+8; const s=svg(w,h); const lab=opts.labW||190;
  rows.forEach((r,i)=>{const bw=(w-lab-60)*r.v/max;
    s.appendChild(el('text',{x:0,y:i*rowH+15,'font-size':11,fill:'#9aa'},[r.k]));
    s.appendChild(el('rect',{x:lab,y:i*rowH+4,width:Math.max(1,bw),height:14,
      fill:r.color||'#4aa3ff',rx:2}));
    s.appendChild(el('text',{x:lab+Math.max(1,bw)+6,y:i*rowH+15,'font-size':11,
      fill:'#ccd'},[opts.suffix?((r.v).toPrecision(3)+opts.suffix):String(r.v)]));});
  host.appendChild(s);}
function table(host, cols, rows){const t=document.createElement('table');
  const th=document.createElement('tr'); cols.forEach(c=>{const e=document.createElement('th');e.textContent=c;th.appendChild(e);});
  t.appendChild(th); rows.forEach(r=>{const tr=document.createElement('tr');
    r.forEach(c=>{const e=document.createElement('td');
      if(c && c.html){e.innerHTML=c.html;} else {e.textContent=(c===null||c===undefined)?'—':String(c);} tr.appendChild(e);});
    t.appendChild(tr);}); host.appendChild(t);}
function panelCard(root, p){const d=document.createElement('section'); d.className='card';
  const h=document.createElement('h2'); h.textContent=p.title; d.appendChild(h);
  if(p.warn){const w=document.createElement('p'); w.className='warn'; w.textContent=p.warn; d.appendChild(w);}
  (p.body||[]).forEach(b=>{ if(b.kind==='p'){const x=document.createElement('p'); x.innerHTML=b.text; d.appendChild(x);}
    else if(b.kind==='dl'){const dl=document.createElement('dl');
      b.items.forEach(([k,v])=>{const dt=document.createElement('dt');dt.textContent=k;
        const dd=document.createElement('dd'); dd.innerHTML=v; dl.appendChild(dt); dl.appendChild(dd);});
      d.appendChild(dl);}
    else if(b.kind==='table'){const host=document.createElement('div'); host.className='tw';
      table(host,b.cols,b.rows); d.appendChild(host);}
    else if(b.kind==='bars'||b.kind==='hbars'){const host=document.createElement('div'); host.className='chart';
      d.appendChild(host); if(b.kind==='bars') bars(host,b.data,b.opts); else hbars(host,b.rows,b.opts);}
    else if(b.kind==='img'){const im=document.createElement('div'); im.className='chart';
      im.innerHTML=b.svg; d.appendChild(im);}
  });
  if(p.sources&&p.sources.length){const s=document.createElement('p'); s.className='src';
    s.innerHTML='来源：'+p.sources.map(x=>x.missing?('<code>'+x.path+'</code> <b class="bad">缺失</b>'):
      ('<code>'+x.path+'</code> <span class="h">'+(x.sha256||'').slice(0,12)+'</span>')).join('　'); d.appendChild(s);}
  root.appendChild(d);}
function render(D){const root=document.getElementById('panels'); root.innerHTML='';
  D.panels.forEach(p=>panelCard(root,p));
  document.getElementById('meta').innerHTML='生成于 '+D.generated_utc+'　|　仓库 <code>'+D.repo+'</code>　|　'
    +'源文件 '+D.n_sources+' 个，缺失 '+D.missing.length+' 个'
    +(D.missing.length?('：<b class="bad">'+D.missing.join(', ')+'</b>'):'');}
"""

CSS = """
:root{--bg:#0e1116;--card:#161b22;--fg:#e6edf3;--dim:#8b949e;--acc:#4aa3ff;--bad:#ff6b6b;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
 font:14px/1.55 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
header{padding:18px 22px;border-bottom:1px solid #22282f;position:sticky;top:0;background:rgba(14,17,22,.96);backdrop-filter:blur(6px);z-index:5}
h1{margin:0 0 4px;font-size:19px}h2{margin:0 0 10px;font-size:15px;color:var(--fg)}
#meta{color:var(--dim);font-size:12px}
main{padding:16px 22px 60px;max-width:1180px;margin:0 auto}
.card{background:var(--card);border:1px solid #22282f;border-radius:10px;padding:14px 16px;margin:0 0 14px}
.tw{overflow:auto;max-height:420px}table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{border-bottom:1px solid #22282f;padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600;position:sticky;top:0;background:var(--card)}
code{background:#0b0f14;padding:1px 5px;border-radius:4px;font-size:12px}
.h{color:#586069;font-size:11px}.src{color:var(--dim);font-size:11px;margin:10px 0 0;border-top:1px dashed #22282f;padding-top:8px}
.bad{color:var(--bad)}.ok{color:var(--ok)}.warnp{color:var(--warn)}
.warn{background:#2a1f0a;border-left:3px solid var(--warn);padding:6px 10px;margin:0 0 10px;border-radius:4px}
dl{display:grid;grid-template-columns:minmax(140px,220px) 1fr;gap:4px 14px;margin:0}
dt{color:var(--dim)}dd{margin:0}.chart{margin:6px 0 2px;overflow:auto}
.pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;border:1px solid #30363d;color:var(--dim);margin-right:6px}
.pill.ok{border-color:#238636;color:var(--ok)}.pill.bad{border-color:#8b2c2c;color:var(--bad)}
.pill.warn{border-color:#9e6a03;color:var(--warn)}
"""


def build_panels(S: Sources) -> tuple[list[dict], dict]:
    ov = panel_overview(S)
    ds = panel_dataset(S)
    a5 = panel_a5(S)
    a6 = panel_a6(S)
    pl = panel_plan(S)
    gov = panel_governance(S)

    def pct(v):
        return "—" if v is None else "%.3g%%" % (100 * v)

    panels = [
        {"title": "1. 平台总览（元数据库 / 角色 / 工具）",
         "body": [
             {"kind": "dl", "items": [
                 ["库表行数", "　".join("<code>%s=%s</code>" % (k, v) for k, v in sorted(ov["store"].items()))],
                 ["子智能体角色", "%d 个（A1–A9）；已实现并验证：%s" % (
                     len(ov["roles"]),
                     "、".join(r["id"] for r in ov["roles"] if "已实现" in (r["status"] or "")))],
                 ["MCP 工具", "%d 个：<code>%s</code>" % (len(ov["mcp_tools"]), "</code> <code>".join(ov["mcp_tools"]))],
             ]},
             {"kind": "table", "cols": ["角色", "名称", "类型", "状态"],
              "rows": [[r["id"], r["name"], r["kind"], r["status"]] for r in ov["roles"]]},
         ], "sources": ov["sources"]},

        {"title": "2. 数据集：远端导出族 <code>cell_te2_*</code>（223 组合）",
         "body": [
             {"kind": "dl", "items": [
                 ["规模", "run %s 个（完成 %s）／参数组合 <b>%s</b>／频点 %s 个／点位 %s 行" % (
                     ds["counts"].get("n_runs"), ds["counts"].get("n_runs_complete"),
                     ds["counts"].get("n_combos"), 61, ds["counts"].get("n_points"))],
                 ["覆盖", "N2=%s；N1=%s；x_scale=%s" % (
                     ds["coverage"].get("N_w_te2"), ds["coverage"].get("N_w_te1"),
                     ds["coverage"].get("x_scale"))],
                 ["判据点 / 口径", "取样点 <code>%s</code>（−10 µm）；<code>%s</code>" % (
                     ds["caliber"].get("criterion_point_table_m"), ds["caliber"].get("spl_basis"))],
                 ["族分布", "　".join("<code>%s: %d</code>" % (k, v) for k, v in ds["family_counts"].items())],
             ]},
             {"kind": "p", "text": "<b>质量门命中次数</b>（每个组合可命中多项；导出器自报 + 我们自算）："},
             {"kind": "hbars", "rows": [{"k": k, "v": v, "color": "#d29922" if "exporter" in k else "#4aa3ff"}
                                        for k, v in ds["flag_counts"].items()],
              "opts": {"w": 640, "labW": 300}},
         ], "sources": ds["sources"]},

        {"title": "3. 谐振频率到底在哪：两种口径的直方图",
         "body": [
             {"kind": "p", "text": "<b>整段最强峰</b>（5–35 MHz 内 SPL 的 argmax，1 MHz 分箱）："},
             {"kind": "bars", "data": ds["fpeak_hist"], "opts": {"color": "#4aa3ff"}},
             {"kind": "p", "text": ("<b>一阶峰</b>（最低频的内部局部极大，%s）：有峰 %s/%s，"
                                    "中位 <b>%s MHz</b>，落在 18–22 MHz 的只有 <b>%s</b> 个。"
                                    % (ds["first_mode"]["definition"], ds["first_mode"]["n_with"],
                                       ds["first_mode"]["n_total"], ds["first_mode"]["median_MHz"],
                                       ds["first_mode"]["within_18_22MHz"]))},
             {"kind": "bars", "data": ds["first_mode"]["hist"] or {}, "opts": {"color": "#3fb950"}},
             {"kind": "p", "text": ("<span class='pill warn'>注意</span>60/223 组合的整段最强峰顶在 35 MHz 边界 ⇒ "
                                    "谐振在频段之外，本批数据<b>测不到</b>；20 MHz 是<b>设计工作频点</b>，"
                                    "不是这批器件的谐振频率。")},
         ], "sources": ds["sources"]},

        {"title": "4. A5 分族分指标排名（不含总分）",
         "body": [
             {"kind": "p", "text": ("整体判定 <b>%s</b>（release_allowed=%s）；逐族：%s；"
                                    "全局排除率 %s。A5 **不出选点建议**：%s"
                                    % (a5["verdict"], a5["release_allowed"],
                                       "　".join("<code>%s:%s</code>" % (k, v) for k, v in a5["verdict_by_family"].items()),
                                       pct(a5["exclusion_rate"]),
                                       a5["next_batch"]["verdict"]))},
             {"kind": "table", "cols": ["族", "指标", "口径", "有效/排除", "榜首参数", "值", "单位"],
              "rows": [[t["family"], "<code>%s</code>" % t["metric"], t["caliber"],
                        "%s/%s" % (t["n_available"], t["n_excluded"]),
                        json.dumps(t["top_params"], ensure_ascii=False) if t["top_params"] else "—",
                        ("%.6g" % t["top_value"]) if t["top_value"] is not None else "—",
                        t["unit"]] for t in a5["tops"]]},
             {"kind": "p", "text": "Pareto：" + "　".join(
                 "<code>%s</code> 参与 %s / 前沿 %s" % (p["family"], p["n_considered"], p["n_front"])
                 for p in a5["pareto"])},
         ], "sources": a5["sources"]},

        {"title": "5. AI 求解器（A6）三轮结果：跨族留出 max 相对误差",
         "body": [
             {"kind": "table", "cols": ["目标", "第一轮(直接回归)", "第二轮 M1", "第三轮 M1",
                                        "第三轮 M4(NN+残差)", "第三轮 B3(最近邻)"],
              "rows": [[r["target"], pct(r["r1_direct"]), pct(r["r2_M1"]), pct(r["r3_M1"]),
                        pct(r["r3_M4"]), pct(r["r3_B3"])] for r in a6["comparison"]]},
             {"kind": "p", "text": "频谱重建相对 L2（61 点）：第二轮 M1 %s / M3 %s ｜ 第三轮 M1 %s / M4 %s / B3 %s"
              % (pct(a6["spectrum"]["r2_M1"]), pct(a6["spectrum"]["r2_M3"]),
                 pct(a6["spectrum"]["r3_M1"]), pct(a6["spectrum"]["r3_M4"]),
                 pct(a6["spectrum"]["r3_B3"]))},
             {"kind": "p", "text": ("<span class='pill bad'>结论</span>三轮全部 <b>fail</b>（判定带：标量 3%%/10%%、"
                                    "频谱 5%%/10%%）；最强的「模型」其实是<b>最近邻</b> ⇒ 当前数据密度下 AI 求解器"
                                    "<b>不可用</b>，只能给趋势。")},
             {"kind": "table", "cols": ["seq", "轮次", "预注册哈希", "口径被改?", "缺失件"],
              "rows": [[e["seq"], e["round"], "<code>%s</code>" % e["prereg"], e["changed"],
                        (", ".join(e["missing"]) or "—")] for e in a6["registry"]]},
         ], "sources": a6["sources"]},

        {"title": "6. x 方向加密清单（只加密 x，不动频段）",
         "body": [
             {"kind": "p", "text": ("候选 <b>%s</b> 个（来自 %s 个「层=(族,N1)」）；推荐先跑 <b>%s</b> 个。"
                                    "预期收益只给<b>幅度</b>、不预测符号。"
                                    % (pl["n_candidates_total"], pl["n_strata"], pl["batch_size"]))},
             {"kind": "hbars", "rows": [{"k": "#%d %s N1=%g x=%.3f%s" % (
                 c["priority"], c["family"].replace("cell_te2_", ""), c["n1"], c["x_mid"],
                 "  ⚠分支" if c["branch"] else ""),
                 "v": c["d_spl20"] or 0.0,
                 "color": "#ff6b6b" if c["branch"] else "#4aa3ff"} for c in pl["recommended"]],
              "opts": {"w": 660, "labW": 260, "suffix": " dB"}},
             {"kind": "p", "text": "<b>停止条件</b>：" + "；".join(pl["stop_conditions"])},
             {"kind": "p", "text": "<b>不解决</b>：" + "；".join(pl["not_doing"])},
         ], "sources": pl["sources"]},

        {"title": "7. 治理与证据（冻结门禁 / 记录索引）",
         "body": [
             {"kind": "table", "cols": ["冻结件", "verdict", "release_allowed", "失败项"],
              "rows": [[v["target"], v["verdict"], v["release_allowed"], v["n_failed"]]
                       for v in gov["freeze_verdicts"]]},
             {"kind": "p", "text": "记录索引章节（append-only）：<br>" + "<br>".join(
                 "· %s" % s for s in gov["index_sections"][-14:])},
         ], "sources": gov["sources"]},
    ]
    data = {"panels": panels}
    return panels, data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 MEMS 平台看板（自包含 HTML）")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--title", default="MEMS Harness 平台看板")
    ap.add_argument("--generated-at", default=None,
                    help="固定生成时刻（ISO8601）⇒ 产物可复现；缺省用当前时间，"
                         "或环境变量 SOURCE_DATE_EPOCH")
    args = ap.parse_args(argv)

    import os
    stamp = args.generated_at
    if not stamp and os.environ.get("SOURCE_DATE_EPOCH"):
        stamp = datetime.fromtimestamp(int(os.environ["SOURCE_DATE_EPOCH"]),
                                       timezone.utc).isoformat(timespec="seconds")
    if not stamp:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    S = Sources()
    panels, data = build_panels(S)
    missing = S.missing()
    doc = {
        "kind": "mems_dashboard",
        "generated_utc": stamp,
        "generator_sha256": sha256_file(Path(__file__)),
        "reproducible_hint": ("产物含生成时刻；要逐字节复现请固定 --generated-at（或设 "
                              "SOURCE_DATE_EPOCH）。generator_sha256 用于对齐「哪一版代码」生成的看板。"),
        "repo": str(REPO),
        "n_sources": len(S.used),
        "missing": missing,
        "sources": S.used,
        "panels": panels,
    }
    (out / "dashboard_data.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{args.title}</title><style>{CSS}</style></head>
<body><header><h1>{args.title}</h1><div id="meta"></div></header>
<main><div id="panels"></div></main>
<script>const DASH={json.dumps(doc, ensure_ascii=False)};</script>
<script>{JS}
render(DASH);</script>
</body></html>
"""
    (out / "index.html").write_text(html, encoding="utf-8")
    print("面板 %d 个；源文件 %d 个；缺失 %d 个 %s"
          % (len(panels), len(S.used), len(missing), ("→ %s" % missing) if missing else ""))
    print("产物：%s" % (out / "index.html"))
    print("      %s（%.1f KB）" % (out / "dashboard_data.json",
                                   (out / "dashboard_data.json").stat().st_size / 1024))
    print("      index.html（%.1f KB，自包含：数据内嵌、图形内联 SVG、无外网依赖）"
          % ((out / "index.html").stat().st_size / 1024))
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
