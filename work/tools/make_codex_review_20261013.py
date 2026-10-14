# -*- coding: utf-8 -*-
"""生成给 **Codex** 评阅的交接件 `docs/CODEX_REVIEW_20261013.md`（LF）。

原则：所有哈希/字节**从磁盘现算**（不凭记忆）；每条主张都挂出处；自身的错误与不主张单列；
并给出**可复现的零求解校验命令**。本脚本本身不改变任何被评阅对象。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "docs/CODEX_REVIEW_20261013.md"

# (标签, 相对路径) —— 全部会被现算 sha256/bytes
FILES = [
    ("S0 预注册", "work/runs/s0-rerun-20261013/PREREG_S0_V2.json"),
    ("S0 预注册行尾对齐留痕", "work/runs/s0-rerun-20261013/PREREG_S0_V2_EOL_ALIGNMENT.json"),
    ("S0 复算结果", "work/runs/s0-rerun-20261013/S0_RESULT_V2.json"),
    ("S0 报告", "work/runs/s0-rerun-20261013/S0_REPORT_V2.md"),
    ("S0 复算脚本", "work/runs/s0-rerun-20261013/s0_rerun.py"),
    ("S3 两分支并置件", "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013.json"),
    ("S3 并置件说明", "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013.md"),
    ("S3 并置件审计", "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_AUDIT.json"),
    ("S3 生效件（分支 B）", "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE.json"),
    ("S3 生效件审计", "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE_AUDIT.json"),
    ("S3 全频段结果", "work/runs/s3-band-20261013/S3_BAND_RESULT.json"),
    ("S3 基线（登记门禁件）", "work/runs/c-batch-20261010/s3_gate_c_batch.json"),
    ("S3 更正口径证据", "work/runs/eda64-20261010/p5_cost/S3_GATE_CORRECTED_CALIBER.json"),
    ("solver_spec（提升后）", "work/runs/solver/pmut-f1/solver_spec.json"),
    ("solver_spec（提升前留档）", "work/runs/solver/pmut-f1/solver_spec.PRE_PROMOTION_20261013.json"),
    ("放行台账（append-only）", "work/runs/solver/pmut-f1/release_log.jsonl"),
    ("状态提升记录", "work/runs/solver/pmut-f1/STATE_PROMOTION_20261013.json"),
    ("门禁原件", "work/runs/eda64-20261010/EDA65_RELEASE_GATE.json"),
    ("门禁 E 轮", "work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013E.json"),
    ("门禁 F 轮", "work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013F.json"),
    ("门禁 G 轮（最新）", "work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013G.json"),
    ("第 6 轮提案", "work/runs/eda64-20261010/GATE_AMENDMENT_20261013F_PROPOSAL.md"),
    ("n4 预注册", "work/runs/eda64-20261010/n4_multifreq/PREREG.json"),
    ("n4 频点解析", "work/runs/eda64-20261010/n4_multifreq/PREREG_STAGE2.json"),
    ("n4 报告", "work/runs/eda64-20261010/n4_multifreq/N4_REPORT.md"),
    ("n4 k 扫描/轴分解", "work/runs/eda64-20261010/n4_multifreq/N4_ROM_DIAG.json"),
    ("n4 九格更正", "work/runs/eda64-20261010/n4_multifreq/N4_CORRECTED_CELLS.json"),
    ("n4 执行台账", "work/runs/eda64-20261010/n4_multifreq/LEDGER.jsonl"),
    ("n4 载体（= M-base）", "work/runs/eda64-20261010/n4_multifreq/input.mph"),
    ("stage-3 表示层预注册", "work/runs/eda64-20261010/n5_stage3/PREREG_REPR.json"),
    ("stage-3 表示层结果", "work/runs/eda64-20261010/n5_stage3/REPR2_RESULT.json"),
    ("stage-3 频率轴重设计结果", "work/runs/eda64-20261010/n5_stage3/S3_STAGE3_RESULT.json"),
    ("#3 预注册草案", "work/runs/eda64-20261010/item3-prereg-20261013/PREREG_ITEM3_FREQUENCY_DESIGN.json"),
    ("#3 成本估算", "work/runs/eda64-20261010/item3-prereg-20261013/COST_ESTIMATE.md"),
    ("#3 重审发现件", "work/runs/eda64-20261010/item3-prereg-20261013/N4_REEXAMINATION_OF_ITEM3.md"),
    ("论文 v13", "docs/PAPER_DAC2027_EN_v13_20261013.md"),
    ("论文 v13 出处", "docs/PAPER_DAC2027_EN_v13_PROVENANCE.md"),
    ("论文 v14（最新）", "docs/PAPER_DAC2027_EN_v14_20261013.md"),
    ("论文 v14 出处", "docs/PAPER_DAC2027_EN_v14_PROVENANCE.md"),
    ("补充材料（v12 时代起未改）", "docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013b.md"),
    ("INDEX 台账", "docs/INDEX-records-and-rulings.md"),
]


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    man = []
    missing = []
    for label, rel in FILES:
        p = REPO / rel
        if not p.is_file():
            missing.append(rel)
            continue
        b = p.read_bytes()
        man.append({"label": label, "rel": rel, "bytes": len(b), "sha256": sha(p)})
    if missing:
        raise SystemExit("[FAIL] 缺件：%s" % missing)
    idx = next(m for m in man if m["rel"].endswith("INDEX-records-and-rulings.md"))
    gate = json.loads((REPO / "work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013G.json")
                      .read_bytes().decode("utf-8"))
    spec = json.loads((REPO / "work/runs/solver/pmut-f1/solver_spec.json").read_bytes().decode("utf-8"))
    s0 = json.loads((REPO / "work/runs/s0-rerun-20261013/S0_RESULT_V2.json").read_bytes().decode("utf-8"))
    s3 = json.loads((REPO / "work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE.json")
                    .read_bytes().decode("utf-8"))
    band = json.loads((REPO / "work/runs/s3-band-20261013/S3_BAND_RESULT.json").read_bytes().decode("utf-8"))
    ks = json.loads((REPO / "work/runs/eda64-20261010/n4_multifreq/N4_ROM_DIAG.json")
                    .read_bytes().decode("utf-8"))["k_sensitivity"]

    def is_zero(a: dict, b: dict, keys) -> str:
        return ", ".join(f"{k}={a.get(k)!r} vs {b.get(k)!r}" for k in keys)

    per_freq_s0 = "\n".join(
        f"| {e['f_MHz']:g} | {e['rho_eff_kg_m3']:.10f} | {e['rel_err']:.4e} | "
        f"{'**超 1 %**' if e['rel_err'] > 0.01 else '阈内'} |" for e in s0["per_frequency"])
    per_freq_s3 = "\n".join(
        f"| {e['freq_MHz']:g} | {e['operative_ftet1']} | {e['resid_17face_pct']:.6f} % | "
        f"{e['margin_ratio_tau_over_resid']:.2f}× |" for e in band["per_frequency"])
    k_rows = "\n".join(
        f"| {r['k']} | {r['energy']:.6f} | {r['train_median_rel_key']*100:.4f} % | "
        f"{r['cross_max_rel_key']*100:.4f} % |" for r in ks["n1_4"]["rows"])
    mf = "\n".join(f"| {m['label']} | `{m['rel']}` | {m['bytes']:,} | `{m['sha256'][:16]}…` |" for m in man)
    codes = "\n".join(
        f"| `{m['sha256'][:16]}…` | {m['bytes']:,} | `{m['rel']}` |" for m in man)

    doc = f"""# MEMS Harness 工作交接与**评阅请求** · 2026-10-13

**收件人**：外部评阅方（Codex）
**作者**：本仓库的执行智能体（DSH / deepseek-v4-flash）
**性质**：**自评材料，不是结论**。请优先攻击第 5 节的清单；凡你认为我越界、口径不成立、或数字不可追溯之处，请直接点名并给出证据要求。

---

## 0. 怎么用这份文件

1. **本件的每条主张都挂出处**；第 6 节给出全部附件的字节数与 sha256（**从磁盘现算**，非记忆）。
2. **零求解可复现**：本轮**没有**任何新的 COMSOL 求解；全部数字来自既有冻结件。可复现校验命令见 §0.2。
3. **本仓库的红线**（评阅时请据此判断我是否越界）：
   - 没有证据不出数字；每个数值必须可追溯到 run/evidence/experiment/feedback id；
   - `None`（无法判定）**永不等于**通过；`inconclusive` 不得写成 pass；
   - 历史 **append-only**：修正靠新增记录，不覆盖既有件；
   - **人保留放行权**：模型状态不得由代码自我晋升；不得把「待验证」写成「已验证」；
   - 阈值与口径**不得事后调整**；事后才声明的口径必须标注 `post_hoc`。
4. **环境事实**（影响复现）：Windows **PowerShell 5.1**（本机**无 `pwsh`**）、**无 git**、Python 用 `work\\.venv\\Scripts\\python.exe`；
   COMSOL 6.4.0.293 在 `D:\\COMSOL64\\Multiphysics`；求解必须**单实例串行**。

### 0.2 可复现的零求解校验（建议评阅者实际跑）

```powershell
$py = ".\\work\\.venv\\Scripts\\python.exe"
# 1) S0 复算（幂等：读冻结件重算，写 S0_RESULT_V2.json）
& $py -X utf8 .\\work\\runs\\s0-rerun-20261013\\s0_rerun.py
# 2) S3 生效件重新审计（用仓库自己的审计器；应 ok=True）
& $py -X utf8 -c "import sys,json,pathlib; sys.path.insert(0,'src'); from memsharness.s3_gate_audit import audit_gate_file; print(audit_gate_file('work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE.json','work/runs/solver/pmut-f1/solver_spec.json')['ok'])"
# 3) 论文验证器（v14 应 pass）
& $py -X utf8 .\\work\\runs\\eda64-20261010\\n5_stage3\\verify_v7.py docs\\PAPER_DAC2027_EN_v14_20261013.md docs\\PAPER_DAC2027_EN_SUPPLEMENT_20261013b.md
# 4) 门禁计数自洽（读 G 件）
& $py -X utf8 -c "import json; d=json.load(open('work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013G.json',encoding='utf-8')); print(d['n_satisfied'],d['n_partial'],d['n_not_satisfied'],d['release_allowed'])"
```

---

## 1. 本轮（2026-10-12 → 13）做了七件事

### 1.1 S0（极限一致性）：**补事前预注册 → 零求解复算 ⇒ `passed`**

- **诉求**：用户裁定「**不接受事后口径 ⇒ 补事前预注册并重跑**」。
- **做法**：先冻结 `PREREG_S0_V2.json`（量、判据频点、阈值、三分支、必报项、限制、不主张），**再**从冻结原始件复算。
- **锚点**：原始件 `s0_close3_result.json` sha `3a508e242951e7671c0139be4a31adc4fe75fcf3f5d7640d08bcce1d8dc02d18`、
  分析件 `c_batch_round2_analysis.json` sha `f3fb1d34f8acf8cf5b1456b39625319188b62ddf0a7fccc7572548632dba3f97` —— 两件实测相符才继续。
- **量**：`rho_eff(f) = hemi_pabs2 / (2·c_model·P_rad)`；该恒等式对单极子是**精确式**（无可调参数）。
- **结果**（判据频点 0.25 MHz，阈 1 %）：

| f (MHz) | `rho_eff` (kg/m³) | `rel_err` | 判定 |
|---:|---:|---:|---|
{per_freq_s0}

- **判定 `passed`**：`rel_err(0.25 MHz) = {s0['verdict']['rel_err_at_lowest']:.4e}`，**余量 {s0['verdict']['margin_ratio']:.1f}×**。
- **与既有分析件逐位相同（6/6 频点的 `rho_eff` 与 `rel_err` 差值全为 `0.000e+00`）** ⇒ 是复现，不是重新拟合。
- **必须同现**：**先注册**的那条口径（空间各向同性 / r⁻¹ 律）**仍 `failed`**：
  0.25 MHz 各向同性偏差 A/B = 0.0063255 / **0.0090833**；r⁻¹ 中位相对偏差 A/B = 0.0289158 / **0.0290035**（阈 0.01）、单调下降 = **False**。
- **四条限制**：① 口径选择本身**仍事后**（预注册只覆盖*评测协议*）；② 残差**非单调**（2 MHz 0.071 % < 0.25 MHz 0.090 %）⇒ ≈0.03–0.09 % 系统底噪；
  ③ 只覆盖**单极子成分**；④ 载体为 λ/5 网格且与 x 族求解器实例的绑定**未做**。
- **载体归属（本轮实测）**：S0 复算所用 `input.mph` sha256 = `0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d`
  = **冻结 FOM M-base 本身**（103,681,444 B）⇒ S0 证据落在冻结 FOM 上（S3/S4 证据在 M-h1um 上，见 1.4/1.5）。

### 1.2 S3：把「能量项已关闭」**对齐**进门禁语义（**两个分支并置，由人签字选 B**）

- **冲突要解决**：人已裁定「能量项关闭」，但 S3 证据件里 `S3_complete` 仍 `false`。
- **为什么不能直接翻**：仓库自己的审计器 `src/memsharness/s3_gate_audit.py` **L69** 写死
  `if expect != "passed" and gate.get("S3_complete") is True: problems.append(...)`；判据本体 `verdict_from_checks()` 是 fail-closed。
- **权威基线**：`c-batch-20261010/s3_gate_c_batch.json`（9 项：7 通过 / 2 失败 / 0 未决）——
  `S3_GATE_CORRECTED_CALIBER.json` 的 `registered_gate` 指向它，论文 v12 §6.4 的计数亦来自它。
- **两处口径**：① 电流守恒（登记口径 **VOID**：电路未闭合 + 后处理法向）⇒ 改「闭合 28 面 + **物理场法向** `es.nx/ny/nz`」⇒ True（人签 2026-10-12）；
  ② 能量项（登记 **False 6.1768 %**，加密后仍不闭合、外推 ≈ −3.78 %）⇒ 人 2026-10-13 在三选一（改口径/改模型/维持失败）中**选改口径**，
  采用 **条文①′**：声学侧闭合面**净外通量**、**17 面**、τ = 0.5 %、取向**逐面实测**。
- **条文①′ 全频段实测**（7/7 ≤ τ）：

| f (MHz) | 判据网格 | 17 面残差 | 余量 |
|---:|---|---:|---:|
{per_freq_s3}

- **生效件**：`S3_ALIGNMENT_20261013_OPERATIVE.json` —— 判定由**仓库判据本体**现算 ⇒
  `verdict = passed`、`n_checks/n_passed/n_failed/n_inconclusive = {s3['gate']['n_checks']}/{s3['gate']['n_passed']}/{s3['gate']['n_failed']}/{s3['gate']['n_inconclusive']}`、
  **`S3_complete = true`**；审计 `ok = {json.loads((REPO / 'work/runs/s3-band-20261013/S3_ALIGNMENT_20261013_OPERATIVE_AUDIT.json').read_bytes().decode('utf-8'))['audit_of_this_file']['ok']}`。
- **负对照（已跑）**：把分支 A 的 checks 放回而 `S3_complete` 仍 true ⇒ 审计器报 4 项问题（含 `S3_complete=True 但判定为 'failed'`）
  ⇒ 证明 `true` 是**由 checks 推出**、非手填。（负对照件写在系统临时目录、跑完即删，仓库不留可误读件。）
- **退役 ≠ 抹除**：电—声一致口径的 **6.1768 %**、趋势 −4.8517/−4.3837/−4.1205、**外推 ≈ −3.78 %** 逐字保留在 `retired_items`。
- **「关闭」随行的限制**：两条声明偏离（`-np` 门禁被覆盖为 8；**逐频点各自网格 ⇒ 35 MHz 判据网格 λ/18、λ/19 无 35 MHz 实测值**）、
  两次基建失败（λ/19/np=8 跑到 17 % 中止 36 min；λ/19/35 MHz/np=16 MUMPS out-of-core `Failed_to_find_a_solution`，DOF 5.13e6）、
  **上边界余量 ≈1.3× 是规则算出来的**（`n = ceil(1.10·n_req)` ⇒ 目标 ≈ τ/1.21 ≈ 0.413 %；判据若改 0.3 % 上边界多数不过）、
  **只动 `ftet1` 一条轴**（选择集 = domain 1）⇒ 非全模型网格收敛、非 Richardson 误差界、**跨频点残差不得互比**。

### 1.3 模型状态提升：`draft → physics_consistent`（走**仓库自己的状态机**）

- **诉求**：第一跳条件（§6.4：S0 + S3）已齐，人裁定「现在提升」。
- **做法**：`src/memsharness/solver.py::apply_state(write=True)` —— **未手写状态**；证据**现算**（S0 取判据频点值；S3 由 checks 经 `verdict_from_checks()` 重推）。
- **结果**：`solver_spec.json` {json.loads((REPO / 'work/runs/solver/pmut-f1/solver_spec.PRE_PROMOTION_20261013.json').read_bytes().decode('utf-8'))['state']!r}
  → `{spec['state']!r}`；字节 2,559 → {man[[m['rel'].endswith('solver_spec.json') for m in man].index(True)]['bytes']:,}；
  **变动的顶层键只有 `['release','state']`**（脚本断言）；`validate_spec()` 通过；提升前字节**逐字节另存**（本仓库无 git）。
- **放行台账**（append-only）追加 1 条：`from: draft → to: physics_consistent`、`auto: true`、
  `levels: {{S0: passed, S1: inconclusive, S2: inconclusive, S3: passed, S4: inconclusive, S5: inconclusive}}`。
- **运行时强制已实测**：`solve()` 仍 `refused=True`、`fallback=comsol` ⇒ **状态提升不等于能出解**（只有 `approved_solver` 才能）。

### 1.4 门禁第 6 轮：`#4` ⇒ `satisfied`（人判 F1）＋ 载体口径 G1 ＋ 两处过时文本更正

- E 轮把 `#4` 的改判条件**自己写死**为「待 ① S0、② 签字」；两件均已就位 ⇒ 依 §225/§227 的证据改判。
- 计数：**{gate['n_satisfied']} `satisfied` / {gate['n_partial']} `partial` / {gate['n_not_satisfied']} `not_satisfied`**；
  `release_allowed = {str(gate['release_allowed']).lower()}`；`verdict = {gate['verdict']!r}`。
- 同时更正两处**过时** gap：`#5` 删「FOM 选谁至今未裁定」（FOM 已于 2026-10-12 冻结为 **M-base**），
  改写为「S4 载体 **M-h1um** ≠ 冻结 FOM **M-base** ⇒ 『在最终 FOM 上』**字面未满足**」；
  `#7` 改写为「电—声功率平衡**仍未闭合**（6.1768 %、外推 ≈ −3.78 %），但**不再是** `#4` 的 S3 失败项」。

### 1.5 `#3` 重审 ⇒ 门禁第 7 轮（**状态维持 `not_satisfied`**，gap 重写）

- **发现**：`work/runs/eda64-20261010/n4_multifreq/` 是一份**已执行完毕**的多频场 campaign，而 `#3` 原文本写「场快照语料 = **仅 20 MHz**」——
  **过时**。实测：预注册 `status = FROZEN_BEFORE_ANY_N4_SOLVE`；载体 `input.mph` sha `0f75ca1d…`（**= 冻结 FOM M-base**）；
  `PREREG_STAGE2.json` 在主批前写死 13 个频点 `6.0/6.3/11.1/11.4/11.76/11.88/12/12.12/12.24/12.6/12.9/18.0/18.9 MHz`；
  30 设计点（每族 12 train + 3 holdout x）；`LEDGER.jsonl` **34 条**全 ok；`aligned/` 35 npz。
- **它产出的结论**：20 MHz 回归靶通过量级对拍（全域 1.2263 % / 1.2997 %，关键区 0.5019 % / 0.5632 %，双方 1369 有限点）；
  **交叉格 S1 失败**：注册口径 `linear`/k=4 关键区 max —— **3/9 格 27.0794 % / 30.8683 %**，
  **9/9 格更正后 27.7575 % / 32.1885 %** ⇒ 最差 **阈值的 16.1×**；变体 9 格 `cubic` 18.87/19.59 %、`rbf_tps` 227.4/356.6 %。
- **定因**：k=4 → k=120 自重构 → 0.000 % 而交叉格不变 ⇒ **不是基截断**（下表）；**预注册的 stage-3「只改频率轴」重设计**后
  最好 `cubic` 仍 **26.46 %**，且单极点谐振**在自己的训练数据上就失败**（训练对照 68.56 % / 76.13 %，`REPR2_RESULT.json` 判 `fail`）
  ⇒ **瓶颈在「表示」**。

| k | 能量 | 训练格自重构（关键区中位） | 交叉格 max（关键区） |
|---:|---:|---:|---:|
{k_rows}

- **新 gap（第 7 轮）**：① 覆盖名义上存在；② 频点集合由**单一先导 `x = 0.60`** 定，而峰位随 x 从 **6.3 MHz 漂到 18.9 MHz**（同件内留出 x 的 `f_pk` 真值 18.9/11.1/6.3）；
  ③ 判据**拒绝**该覆盖（13.9× / 16.1×）；④ **端口频响未导出**；⑤ 关闭此条**不是**「再加密采样」——瓶颈在**表示**。

### 1.6 论文 v13 → v14

- **v13**（由 v12 经 9 处单命中替换）：补 **S0 段**与门禁语义 S0 行；**S3 改三段式**（登记 7/2 → 首个人签口径 **8 passes and 1 failure** → 第二个人签口径 ⇒ 九项全过），
  并写明「**通过记录的是两个被裁定的口径，不是功率平衡**」；§6.5 补「该口径已被采纳为 S3 能量判据」；摘要改「Two results are negative and one is scoped」；限制补「两跳条件已满足但**未提升状态**」。
- **v14**（由 v13 经 **1 处**替换）：摘要「misses the 2 % key-region threshold by **10×**」→
  「misses the 2 % key-region criterion by **27.76 %** and **32.19 %** on its two families (**13.9×** and **16.1×**)」。
  **原因**：10× 蕴含 20 %，而产物里没有这个数 ⇒ **低估且不可追溯**；正文 §6.x **本来就写对了**（27.76 %/32.19 %），本版只把摘要对齐正文。
- **共同自检**：往返**逐字节还原上一版**、双盲扫描干净、无 CRLF、报告哈希**从磁盘算**；`verify_v7.py` ⇒ **pass**（v6 的 43 个 headline 全在正文）。
- 正文词数：v12 4,839 → v13 5,225 → **v14 5,234**；含 AI 与参考 5,822；**本机无 TeX，页数未编译验证**。

### 1.7 `#3` 预注册**草案** + **实测**成本模型（人裁定：先出件、不跑求解）

- 状态 **`DRAFT_NOT_FROZEN`**：协议 §5 的字段里 4 项待裁定 **O1–O4 现已裁定**（见 §7）。
- **实测成本**（来自 S3 全频段件逐 run 的 `solve_wall_s ÷ 频点数`）：

| 网格 | 单元数 | DOF | 建模 (s) | **每频点求解 (s)** |
|---|---:|---:|---:|---:|
| λ/5 | 342,886 | 900,431 | 0.05 | **74.6** |
| λ/9 | 592,560 | 1,239,686 | 6.2 | 91.9 |
| λ/11 | 862,410 | 1,603,812 | 9.3 | 156.4 |
| λ/13 | 1,263,824 | 2,144,396 | 12.4 | 278.1 |
| λ/16 | 2,172,398 | 3,366,598 | 22.0 | 578.5 |
| λ/18 | 2,999,251 | 4,476,473 | 19.9 | 1575.5 |
| λ/19 | 3,489,637 | 5,134,258 | — | **失败**（MUMPS out-of-core） |

- 工作量 **329 次频域解**（312 主批 + 9 交叉留出 + 8 先导）⇒ **λ/5 约 6.81 h**；λ/9 档 8.40 h。
- **更正两处**：协议旧估计「35–50 s/点 ⇒ 3–4.5 h」偏乐观 1.5–2.3×；
  我先前说过的「**~17 s/频点**」是**错的** —— 它来自 S0 的 `s0_close3` 运行，而该件 `study.run(` 出现 **0** 次（**纯后处理**，6 频点共 12.7 s）。

---

## 2. 关键数字台账（每条挂出处件 + sha）

| 数字 | 值 | 出处 |
|---|---|---|
| S0 判据频点 rel_err | `{s0['verdict']['rel_err_at_lowest']:.4e}`（余量 {s0['verdict']['margin_ratio']:.1f}×） | `S0_RESULT_V2.json` `{sha(REPO / 'work/runs/s0-rerun-20261013/S0_RESULT_V2.json')[:16]}…` |
| S0 旧口径（各向同性 / r⁻¹） | 0.0090833 / 0.0290035（`failed`） | `c-batch-20261010/s0_lowfreq/s0_limit_analysis.json` |
| S3 17 面全频段残差 | 0.034639 / 0.136818 / 0.206549 / 0.365297 / 0.377494 / 0.353731 / 0.382620 % | `S3_BAND_RESULT.json` `{sha(REPO / 'work/runs/s3-band-20261013/S3_BAND_RESULT.json')[:16]}…` |
| 退役口径读数 / 外推极限 | 6.1768 % / ≈ −3.78 % | `S3_ALIGNMENT_20261013_OPERATIVE.json` `retired_items` |
| 门禁计数 | {gate['n_satisfied']} / {gate['n_partial']} / {gate['n_not_satisfied']}，`release_allowed={str(gate['release_allowed']).lower()}` | `EDA65_RELEASE_GATE_AMENDED_20261013G.json` `{sha(REPO / 'work/runs/eda64-20261010/EDA65_RELEASE_GATE_AMENDED_20261013G.json')[:16]}…` |
| n4 20 MHz 回归靶 | 全域 1.2263 / 1.2997 %；关键区 0.5019 / 0.5632 % | `n4_multifreq/N4_REPORT.md` |
| n4 交叉格（注册口径） | 3/9 格 27.0794 / 30.8683 %；**9/9 格 27.7575 / 32.1885 %** | `N4_CORRECTED_CELLS.json` |
| n4 k=120（9 格） | 27.6424 / 31.7912 % | `N4_ROM_DIAG.json` `k_sensitivity` |
| stage-3 频率轴重设计最好值 | `cubic` 26.46 % | `n5_stage3/PREREG_REPR.json` `why_now` |
| 单极点谐振训练对照 | 68.56 / 76.13 % | 同上 |
| 论文 v14 摘要 | 27.76 % / 32.19 %（13.9× / 16.1×） | `PAPER_DAC2027_EN_v14_20261013.md` `{sha(REPO / 'docs/PAPER_DAC2027_EN_v14_20261013.md')[:16]}…` |

---

## 3. 当前状态（一句话版）

- **门禁**：`release_allowed = false`；{gate['n_satisfied']} satisfied / {gate['n_partial']} partial / {gate['n_not_satisfied']} not_satisfied；**唯一 `not_satisfied` = `#3`**。
- **模型状态**：`solver_spec.state = {spec['state']}`（**不是** `solver_certified`/`approved_solver`）；`solve()` 实测仍拒答。
- **论文**：v14 为最新候选（未编译、页数未知）；v6–v13 与三份补充材料快照保留。
- **INDEX**：§1–§232，{idx['bytes']:,} B，sha `{idx['sha256'][:16]}…`（本轮新增 §225–§232）。

---

## 4. 我本轮**自己**犯并已更正的错误（请据此判断我的可靠性）

| # | 错误 | 类别 | 处置 / 固化规则 |
|---:|---|---|---|
| 1 | 预注册 JSON 里混入 ASCII 双引号 ⇒ `json.loads` 报错 | **同类第 6 次** | 改「」；**中文语境一律用「」，禁止在 JSON/Python 双引号串内用 ASCII `"`** |
| 2 | 运行产物行尾写成 LF（同族是 CRLF） | 惯例 | 统一 CRLF，并用**归一化字节相等**自证「只动行尾」 |
| 3 | S3 对齐首版**选错基线**（用 `p2/s3_gate_expand.json` 而非登记件 `s3_gate_c_batch.json`） | **证据选取** | 已 append-only 更正（§226）；**只认 `registered_gate` 指向的件 + 已签更正，不得按时间戳挑基线** |
| 4 | v13 首版把 v12 的中间态计数「8 passes and 1 failure」删掉 ⇒ 被验证器判 **fail** | 叙事编辑 | 改回三段式；**修叙事时不得删掉已被验证器锁定的历史数字** |
| 5 | 生成器的 `gate_item` 字典漏了一个右花括号 ⇒ `SyntaxError` | 代码 | 写了 `work/tools/scan_brackets.py` 定位；**长嵌套字面量出错先用工具定位，别靠眼睛** |
| 6 | 我把「~17 s/频点」当求解成本（实为**后处理**耗时） | **数字口径** | 已更正；**引用耗时前先确认该运行是否真的求解**（判据 = java 里 `study.run(` 出现次数） |
| 7 | 脚本用 `%` 格式化中文文本 ⇒ `TypeError` | **同类第 7 次** | 改哨兵 `@X@` + `.replace()`；**中文文本禁止 `%` 格式化与 f-string 混用百分号** |
| 8 | §231 里那件产物的字节/sha **写在改件之前** ⇒ 记录与磁盘不符 | 记录纪律 | §232 更正；**先定稿、再算哈希、再写记录** |
| 9 | 我推测「逐设计点开窗可修 `#3`」——**被仓库已有预注册实验否证** | **推测当结论** | 已从 gap 剔除（§232 `self_correction`）；**报机制前先检索仓库是否已有针对它的预注册实验** |
| 10 | 门禁 `chain` 每轮前置 BASE ⇒ 11 条里 `EDA65_RELEASE_GATE.json` 重复 5 次 | 外观 | 已登记；**不影响任何 sha 正确性**，下一轮去重，不追改历史件 |

---

## 5. 请评阅方**重点评估**的 12 个问题

> 我**不自评通过**。以下每条都可能是我越界或口径不成立之处，请直接判「成立 / 不成立 / 证据不足」，并指出我该补什么。

1. **S0 的「事前」强度够吗？** 预注册只覆盖*评测协议*，而**口径（ρ_eff 恒等式）本身是在旧口径失败之后由人裁定采纳的**。
   我把这层事后性写进件里了，但**结论仍标 `passed`** —— 这是否构成「事后洗白」？是否应改标为 `post_hoc_protocol_only`？
2. **阈值书写不一致**：我的预注册写 `rel_err <= 0.01`，而仓库 `evaluate_levels()` 用 `< 0.01`。本值 9.038e−04 在两种写法下都过（余量 11×），
   但我只把它登记为「口径注记」——是否应升级为**必须修正的口径不一致**？
3. **S3 的改判强度**：把登记口径的一个**硬 `False`（6.1768 %，外推 ≈ −3.78 %）**以「改口径」方式退役，
   使 9/9 全过、`S3_complete = true`。**这是否等价于下调了通过标准？** 若你认为过强，请指出应改成什么（例如把 `S3_complete` 保持 false、只留 `S3_energy_item_complete`）。
4. **`S3_complete = true` 由脚本写入**是否符合「人保留放行权」？我的依据是「人已在选择题里签字 + 判定由仓库判据本体现算」，
   但**字段翻转本身是脚本做的** —— 是否需要人**在件上手写签名**才算？
5. **状态提升是否越界**：§6.4 明文写 `draft` + S0/S3 双过 ⇒ 可 `physics_consistent`，我据此提升。
   但同一时刻 `#5` 仍 `partial`（S4 在 M-h1um、非冻结 FOM），且 S3 证据载体 ≠ 冻结 FOM。**该不该提升？**
6. **门禁 `#4` 的 `satisfied` 是否应与载体口径绑定**？我把它写成「S3 在 M-h1um 上通过」的边界注记，**但没有降低 #4 的等级**。是否应降为 `partial`？
7. **`#3` 的三条理由是否过苛/不足**？覆盖读法（⇒ satisfied）与质量读法（⇒ not_satisfied）我选了后者。**你选哪个？为什么？**
8. **n4 的 3 格 vs 9 格**：门禁件与论文正文现在都引 **9 格**值（27.76/32.19）。是否需要**在门禁件里同时列出 3 格值**（我曾把 3 格值写进提案，后被替换）？
9. **又一处数字不一致（请判以哪个为准）**：`n4_multifreq/N4_REPORT.md` 的限制段写
   「k=120 ⇒ 交叉格**稳定 18.52 % / 27.61 %**」，而 `N4_ROM_DIAG.json` 的 k 扫描平台值是 **27.6424 % / 31.7912 %**（与论文正文一致）。
   **18.52 % 在我查到的产物里找不到出处。** 是否需要对 `N4_REPORT.md` 出 append-only 更正？
10. **论文 v14 的改法**：我只把摘要数字对齐正文。是否还应补一句「该多频判据在门禁上**仍未满足**（`#3`）」？
    以及：正文 §6.x 说「frequency sampling was *not* the binding constraint」，而我在 `#3` 的 gap 里写「瓶颈在表示」——**两处措辞是否需要在论文里统一**？
11. **成本估算口径**：我用「run 总求解时间 ÷ 该 run 频点数」。逐频点后是**单调**的（74.6 → 91.9 → 156.4 → 278.1 → 578.5 → 1575.5 s），
    但**总量**看起来非单调（λ/9 643 s vs λ/11 313 s）——**这类口径是否可接受？是否应改为逐档单独求解计时？**
12. **门禁 `chain` 重复 BASE**：是否应立即 append-only 出一件「链条去重」记录，还是留到下一轮自然去重？

---

## 6. 附件清单（字节数与 sha256 **从磁盘现算**）

| 标签 | 路径 | 字节 | sha256（前 16） |
|---|---|---:|---|
{mf}

---

## 7. 待裁定与未完成

### 7.1 本轮已裁定的 4 项（`#3` 预注册的开放字段）

- **O1 载体** = **M-base**（冻结 FOM，本地，103,681,444 B）⇒ 与 G1 裁定（维持 M-base 为冻结 FOM）一致，且 S0 已在它上验过。
- **O2 场变量名** = 用 M-base 的 `p` / `acpr.p_t`，并在**同一变量**上重导 20 MHz 回归靶（新件，旧语料不动）。
- **O3 主批 x 集合** = 协议默认（`N1 ∈ {{4,7}}` × 每族 12 x = 24 点，train_x 已在 `n4_multifreq/PREREG.json` 里写死）。
- **O4 网格口径** = 固定 λ/5（fmax = 35 MHz），并披露该口径下闭合面净通量残差在频段内 0.0567–4.9503 % 属**真值数据自身属性**。

### 7.2 仍未完成

- **论文 v14 未编译**（本机无 TeX）⇒ 页数与是否需要削减未知（削减候选块已在 INDEX §228 量化）。
- **`#3` 是否启动**：预注册草案与成本已备（329 次解、约 6.8 h）；**但按 1.5 的定因，正确的下一步是「表示层改造」而非再采样** ⇒ 需要一次**新的**预注册。
- **其余 5 项 `partial`**（`#1` FOM 契约签字与标签映射、`#2` 未见频率、`#5` S4 载体与独立确认、`#7` 端口契约与功率平衡、`#9` POD 在线耗时与 break-even）**均未关闭**；
  即使 `#3` 关闭也只是 5/5/0，**`release_allowed` 仍为 `false`**。

---

## 8. 本件的不主张

- 本件**不构成结论**、**不构成放行**、**不提升任何状态**；
- **不主张** S3 通过等价于功率平衡或能量守恒；**不主张** S0 通过等价于可免 COMSOL 出解或网格无关；
- **不主张** `#3` 已满足；**不主张** n4 的结论无瑕（S2 为 13 点粗口径、S5 未评估、跨平台 ~1e-4）；
- **不主张**表示层改造一定能过判据（**未做**该判定）；**不主张**任何工程绝对值。

---

*生成：{time.strftime('%Y-%m-%d %H:%M:%S')}；生成器 `work/tools/make_codex_review_20261013.py`；所有哈希由该脚本在运行时从磁盘读取后计算。*
"""
    if "\r\n" in doc:
        raise SystemExit("[FAIL] 生成文本含 CRLF")
    OUT.write_bytes(doc.encode("utf-8"))
    back = OUT.read_bytes()
    if b"\r\n" in back:
        raise SystemExit("[FAIL] 落盘出现 CRLF")
    print("写出 %s：%d B，sha256 %s" % (OUT.name, len(back), hashlib.sha256(back).hexdigest()))
    print("附件 %d 件；INDEX %d B（sha %s）；门禁 %d/%d/%d；spec.state=%s"
          % (len(man), idx["bytes"], idx["sha256"][:16], gate["n_satisfied"], gate["n_partial"],
             gate["n_not_satisfied"], spec["state"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
