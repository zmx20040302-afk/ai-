
### L.6 E3 证据包在落地后被**重生成**（另一执行者）⇒ §6.5 分桶表据新 E3 改写；v5 哈希**再次更新**

> 追加原因：§L / §L.5 写就后，**同一工作区内的另一执行者**在 **09:54:53** 把整包 `work/runs/paper-evidence-20261009/`（E1–E9 的 md/json/csv ＋ `MANIFEST.json`/`MANIFEST.md`）**就地重生成**（全部 mtime = `2026-10-09 09:54:53`，**非 append-only**）。这使 §L.1 的若干 E3 引用口径过期 ⇒ 按 append-only 追加本节，**§L/§L.5 原文一字未改**。

| 项 | §L / §L.5 写就时（旧 E3） | 重生成后（现 E3） |
|---|---|---|
| `E3_refusal_grid_points.csv` sha256 | `7867df3953d0662135f657336452f6388f8d7748c202bb46ae651133624b56db`（§103 K-02 登记值） | **`0248bd74ee912d9c968b27d5de68ac0fa3b7678d53f26079d785b8170871dec0`**（33,291 B，476 行） |
| 该 CSV 的 `mode_or_reason` | 自报标签含 `n2_out_of_domain` **102** | **`layer_does_not_exist` 102 ＋ `x_outside_layer_range` 51 ＋ `in_layer` 323**（＝ 476，逐行核对） |
| `E3_refusal_screen.json` | `refusal_reasons_as_reported` = `n2_out_of_domain` 102 ＋ `x_outside_layer_range` 51 | `ccc5e919b7f31bc0…`（3,607 B）：`{layer_does_not_exist: 102, x_outside_layer_range: 51}`；`label_collision` = `{}` |
| `E3_refusal_histogram.csv` | 桶计数自洽（102 / 51 / 102 / 0 / 323 / 0，注明双列 102） | `faf6ab9ad5469f84…`（298 B）：**半更新、内部不自洽** —— `n2_out_of_domain` 与「实测 `layer_does_not_exist`」两行均写 **0**，各桶之和 **374 ≠ 合计 476** |
| `E3_refusal_screen.md` | §2 表与上文一致 | `ba56f693bfabeb0a…`（3,515 B）：§2 表同样半更新（0/51/0/0/323/0，合计仍写 476），而 §2 正文仍写「已报出的两项是 …`n2_out_of_domain` **102**」 ⇒ **表与正文互相矛盾** |

- **本轮据此对 v5 做的 3 处新改动（编号 Y1 / Y2 / Z，改动总数 24 → 27）**：
  1. **Y1**（§6.5 第三条）：改为「前者正是那 102 条的**真实触发**（修复前曾被**标签碰撞**误报为 `n2_out_of_domain`，该碰撞**已按裁决修复**）」；
  2. **Y2**（§6.5 分桶表）：**整块改写为修复后的 E3 口径** —— 桶 = `layer_does_not_exist` 102 ／ `x_outside_layer_range` 51 ／ `n2_out_of_domain` **0** ／ `in_layer` 323 ／ `n2_extrap` 0 ／ 合计 476，并注明来源 = **逐点 CSV（含 sha256）＋ `E3_refusal_screen.json`**；另加两段：**修复前自报标签的历史事实**（`n2_out_of_domain` 102，见 `INDEX §101.5/§102/§104/§105`）与 **⚠️ 证据内部不自洽的如实登记**（374 ≠ 476；以逐点 CSV/JSON 为准，**不改 `work/runs/`**）；
  3. **Z**（§6.5 限定段首句）：`自报标签 …` → `**修复前的**自报标签 …（该碰撞**已按裁决修复**，见 ①）`，并把末句改为「E3 逐点明细与 `E3_refusal_screen.json` 已按修复后的代码重生成，本节分桶表即以当前自报标签 `layer_does_not_exist` 列出」。
- **其余数字经复核未变**（故 §L.1 各条依据仍然成立）：E2 仍为 C `2.7481/3.6648/4.6123`（n=1523）、A `2.8257/3.9433/4.5822`（n=154）、池化 `3.686084`（n=1677）；E6 仍为删失 `92`（36.8%）/ 截断 `103`（41.2%）/ `Q=nan` `39`（可用内 `38`）/ Q 可判定 `108` / 达标 `40`；E7 仍为净可用 **46**、叠加 Q 门禁 **11**（分母 **32**）；E8 仍为 `446 = 162 + 224 + 60`、`83` vs `117`（虚高 34）。
- **交付值（本节为最终登记值）**：`docs/PMUT_DAC2027_初稿_v5_20261009.md` = **`2daf0cdf7340014475c1af4fc9f85f1ad6d17c9e9f871a24af2b0b81f86dcf27`（74,416 B / 627 行 / 纯 CRLF，27 处改动）**；改动说明 = `docs/PAPER_REVISION_LOG_20261009.md`（含 §L、§L.5、§L.6）。
- 说明：若其他执行者**再次**改动 `src/` 或 `work/runs/paper-evidence-20261009/`，本节登记值即随之过期；本执行者以**交付说明中给出的最后一次实测哈希**为准，**不再追改**。
- **纪律不变**：本执行者**零写入 `src/`、`tests/`、`work/runs/`**（上表变化均非本执行者所为）；**未跑 COMSOL、未提升任何状态**（`solver_spec.json` 仍 `state=draft`、`multichannel_model.json` 仍 `status=draft`）。
