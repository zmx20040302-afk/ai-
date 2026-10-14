# 内部溯源件（**不进投稿**）：英文稿 **v3** 的数字溯源与注册用摘要

- 生成：%s；由 `work/tools/make_dac2027_en_v2.py` 从 v1 拆出（**正文数字一字未改**）。
- 投稿候选：`docs/PAPER_DAC2027_EN_v3_20261011.md`（v3 由 v2 生成；改动见 `work/runs/eda64-20261010/p5_cost/V3_GENERATION_REPORT.json`）。
- 为什么拆出：本件含仓库路径/文件名/sha256，**双盲与篇幅都不允许**出现在投稿件里。

## A. Stage-1 注册摘要（DAC 2027 要求 *approximately 100 words*，2026-11-11 截止）

> An abstention-aware surrogate flow for PMUT design-space exploration is presented and
> stress-tested. Resonance-semantic labelling marks censored and unclosed labels; a layered
> surrogate handles mixed continuous–discrete inputs; calibrated intervals are reported with
> their empirical coverage; and out-of-domain queries are refused and referred back to the
> finite-element solver. Evidence is reported per corpus, never pooled. Three results are
> negative, including a physics-consistency gate that fails on energy closure. A
> pre-registered fixed-budget closed loop reaches zero simple regret after five evaluations.

（词数由脚本统计并写进生成报告；**若与系统字数上限冲突，以系统为准**。）

## B. v1 §9 原文（数字溯源表，逐字保留）

## 9. Number provenance

| tag | quantity | source artifact |
|---|---|---|
| | row counts, closed-bandwidth and Q-gate counts (§6.1, re-derived for this draft) | `work/runs/first-peak-20260929/multichannel_labels.csv` (`bandwidth_closed`, `q_gate_pass`, `q_gate_range` = 2.5–3.5; 2005 rows = 1782 C + 223 A); row totals cross-checked against `work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv` (2255 rows = 1782 + 223 + 250) |
| | bandwidth caliber medians, p90, Spearman, Q correlation | `work/runs/first-peak-20260929/bw_method_validation.json`; `bandwidth_crosscheck.json` |
| | baseline table, duplicate-column finding, 20 decidable cells | `work/runs/eda64-20261010/n2_baselines/` (`baselines_by_seed.json`, `N2_REPORT.md`, `MANIFEST.json`) |
| | leakage 0/5, persistence median, manifest hashes | `work/runs/eda64-20261010/n2_verify/` |
| | 9 checks, metrics, thresholds | `work/runs/c-batch-20261010/s3_gate_c_batch.json` |
| | nine-level ladder, key region, Richardson | `work/runs/s4-ftet-ladder-server-20261009/S4_FTET_REPORT.json` (six-level set) **and** the nine-level extension recorded in `work/runs/field-expansion-20261009/` / `INDEX §152` — **the 0.6753 % / 1.5504 % / 1.3446 % / 1.4300 % / 1.4963 % figures come from the latter and were quoted here from the working draft, not re-read** |
| | strict L1 record, mesh caliber, memory failure, server four-level ladder | `validation` table records `val-pmut-l1-mesh-20261001` (`passed = false`, max adjacent 2.235 %), `val-pmut-l1-mesh-x050-attempt-20261001`, `val-pmut-l1-segregated-route-20261003` (route infeasible through the API; server ×0.5 peak 54.08 GB), `val-pmut-l1-mesh-4level-20261003` (strict rule still false, finest pair inside 1 %); mesh caliber and the local ×0.5 memory failure also in `work/runs/eda64-20261010/n1c_mesh_study/` |
| | 0/7, 0/7, 2/7 field-level objects with maxima and models | `work/runs/te2_8_pod_fields_20261005/pod_pipeline_x020_v2/gate_verdict_field_rel_L2.json` and `…_thr5pct.json`; three-object ruling `work/runs/field-expansion-20261009/A4_THRESHOLD_OBJECTS_RULING.md`; fold-pass discipline in the S2 re-check record |
| | local x-family S1/S2 values and the supplemental 8-fold S5 | `work/runs/te2_8_pod_fields_20261005/x_family/n1_4/pod_report_x_n1_4.json` (and `n1_7/`), `s5_8fold_n1_4.json` / `s5_8fold_n1_7.json` (both `supplemental: true`); four caveats summarised in `docs/PLAN_EDA65_20261010.md` P1-1/P1-4 |
| | probe table, calibrated residual, caliber limits | `work/runs/eda64-20261010/N1_PORT_ENERGY_DIAGNOSIS.md` |
| | label semantics, abstention rules | `src/memsharness/`, `WORKING_PLAN.md` §6.1.1/§6.4 |
| | pre-registration, results, independent verification, figure 5 | `work/runs/eda64-20261010/n3_dse/PREREG.json`, `N3_DSE_RESULT.json`, `N3_DSE_REPORT.md`, `N3_INDEPENDENT_VERIFICATION.json`, `LEDGER.jsonl`; `work/runs/eda64-20261010/n5_figures/fig5_dse_closed_loop.pdf` |
| | pre-registration, stage-2 frozen frequencies, results, diagnosis | `work/runs/eda64-20261010/n4_multifreq/PREREG.json`, `PREREG_STAGE2.json`, `N4_RESULT.json`, `N4_REPORT.md`, `N4_ROM_DIAG.{json,md}`, `LEDGER.jsonl`, `README.md` |

**Must be resolved before submission** (tracked, not hidden): re-read the ``-nine-level figures
from their own artifact (`field-expansion-20261009`) rather than from the working draft; compress the
abstract to ≤150 words (it currently over-runs because the closed-loop and multi-frequency results
were added); add figures 1–5 (now generated, but **not yet visually inspected** — the agent cannot
read images); and translate the internal revision log into a reviewer-facing summary. The ``,
``, ``, ``, ``, ``, ``, ``, `` and `` numbers
were re-derived from their authoritative artifacts (label table, `validation` table, gate JSONs,
append-only ledgers, ROM diagnosis, run directories) for this draft, with their calibers named.

## C. v3 新增数字的溯源（P5-1 / P5-3，全部零求解）

| 标签 | 量 | 来源产物 |
|---|---|---|
| [P5-1] | 两载体同口径能量并置：P_in/P_asi/P_hemi、缺口 −4.85 % / −4.12 %、跨载体 ≤0.81 % | `work/runs/eda64-20261010/p5_h1um/P5_H1UM_RECALIBER.json`；原始 `P5_H1UM_REMEASURE_RAW.json`；载体 sha256 `6005ca65…`（185,349,336 B） |
| [P5-3] | 逐频点功率平衡（缺口随频率变号：+3.14…+3.97 % / −1.52…−0.82 %；另一几何 +1.60 % / −0.34 %）；Z(f) 无源必要条件逐点通过；后处理法向缺陷在载体 B 复现（8.2e-04 vs 0.999） | `work/runs/eda64-20261010/p5_port/P5_PORT_CONTRACT_AND_PASSIVITY.json`、`P5_PORT_PROBE_RAW.json` |
| [P5-3c] | 成本/break-even（在线 0.0011 ms、内存 20.14 MB、N* ≈ 150 / 37） | `work/runs/eda64-20261010/p5_cost/SIX_CARRIER_COST_AND_BREAKEVEN.json`、`ONLINE_LATENCY.json` |
