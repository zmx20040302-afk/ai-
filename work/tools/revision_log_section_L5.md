
### L.5 落地后更新（**代码状态在 §L 写就之后发生变化** —— 分类碰撞修复已由另一执行者完成）

> 追加原因：§L.1 的 **L-11 / L-12** 与 §L.4 的第 3 条写就时（本机 09:51–09:54），分类逻辑**仍是旧版**，故当时如实写「**已裁定修复、执行中**」。
> 随后**同一工作区内的另一执行者**在 **09:52:18 / 09:52:55** 落地了修复与新用例 ⇒ 按 append-only，**本节追加更正，§L.1/§L.4 原文一字未改**。

| 项 | §L 写就时（实测 09:51） | 落地后（实测，本机 09:52+） |
|---|---|---|
| `_classify_refusal('该层不存在：要求 N_w_te1 < N_w_te2')` | `n2_out_of_domain`（**碰撞**） | **`layer_does_not_exist`（已纠正）** |
| 真 `N_w_te2` 越域（如 `N_w_te2 必须在 [5, 9]`） | `n2_out_of_domain` | `n2_out_of_domain`（**未变**） |
| `src/memsharness/multichannel_surrogate.py` | sha256 `81df9ca0935d3d7a1bb3b6b2344afec7ffb2d5461119e73ad860bf1bec2d1f4b`，20,894 B，mtime `2026-09-30 09:01:23` | sha256 **`7ec83d3d83c58004aaa1a9f6fbf0d70ed9bd3e1b67c89db3c581665a0d063ff4`**，21,526 B，mtime **`2026-10-09 09:52:18`** |
| 回归用例 | 无 | 新增 **`tests/test_mc_refusal_classification.py`**（sha256 `a33cadfdfd5bb6c60bd3881917f6cdad141756b865c091fc300ec29c1a60819a`，8,057 B，mtime `2026-10-09 09:52:55`） |
| 隔离读取（`excluded_quarantine`） | `predict()` 不读取 | **仍未读取 —— 全文仅出现在 `model_card()`（L112）；`predict()`(L222) / `check_domain()`(L168) 均无该分支** ⇒ \\(I_{iso}\\) **仍为未生效的披露项**（裁决 2 的「隔离读取另议」**未变**） |

- **修复内容（来源：该文件 `_classify_refusal()` 文档串原文）**：把 `("layer_does_not_exist", "该层不存在")` 提到 `("n2_out_of_domain", "N_w_te2")` **之前**；自陈「**本轮修法只调次序、不动任何模式与阈值**，故只有「层不存在」这一类的归属会变」。
- **本轮以只读方式实跑该新用例**：`work\.venv\Scripts\python.exe -X utf8 -m pytest tests\test_mc_refusal_classification.py -q -p no:cacheprovider` ⇒ **9 passed**。其 ③ 号聚合用例以冻结 CSV `work/runs/paper-evidence-20261009/E3_refusal_grid_points.csv` **逐点**比对「接受/拒答判定」，并断言修复后该网格 `layer_does_not_exist` **102** ＋ `x_outside_layer_range` **51** = 153、`n2_out_of_domain` **0**、接受 **323**、网格 **476** ⇒ **聚合账不变、只有标签归属迁移**（与 §L.1 L-11 的分析一致）。
- **论文措辞更正（v5，24 条改动的**同一集合**，仅 3 处文字在重生成时更新）**：头注 ② 改为「**已按裁决修复**（另一执行者完成；本稿交付前实测归类已纠正）」；§6.5 限定段 ① 改为「**分类碰撞 —— 已按裁决修复**」并补实测与新 sha256、新用例与 9 passed、聚合账不变、以及「本节上表与直方图是**修复前**冻结产物（E3），重新筛查时应预期自报标签为 `layer_does_not_exist`」；§4.3 限定段补「（已完成）」。
- **v5 哈希因此更新**：`3be3d753566c4602fcefee476f3d6abf0322de7f8557b3bddc84fb72d93c9135`（72,127 B，§104 登记值） ⇒ **`2a473965b7c46bb3380eb70cb1e846b3fa857c57d96c975c61404aeb69788e93`（72,975 B / 624 行，最终交付值）**。
- **§L.4 第 3 条据实更正**：本轮**确实只跑了一个测试文件**（上列新用例，9 passed，只读、`-p no:cacheprovider`）；**全量 pytest 未跑**。且因**另一执行者**已修改 `src/memsharness/multichannel_surrogate.py` 并新增 `tests/test_mc_refusal_classification.py`，§L.4 中「基线 `686 passed / 5 skipped` 不变」这一表述**已不适用于当前工作区**（该历史基线对应的 `src/` 已被他人变更；**本次变更不是本执行者所为**）。
- **纪律不变**：本执行者**零写入 `src/`、`tests/`**（两处变更均非本执行者），**未改数据、未跑 COMSOL、未提升任何状态**（`solver_spec.json` 仍 `state=draft`、`multichannel_model.json` 仍 `status=draft`）。
