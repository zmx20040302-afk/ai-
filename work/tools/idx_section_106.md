## 106. 更正（紧接 §105，append-only）：**E3 证据包在落地后被重生成**（另一执行者，09:54:53）⇒ 论文 §6.5 分桶表据新 E3 改写、v5 哈希再次更新，并登记 **E3 分桶文件内部不自洽**（**§105.2/§105.3 的对应项被本节取代**，§105 原文一字未改）

> 背景：§104 / §105 写就后，**同一工作区内的另一执行者**在 **09:54:53** 把整包 `work/runs/paper-evidence-20261009/`（E1–E9 ＋ `MANIFEST.json`/`MANIFEST.md`）**就地重生成**（非 append-only）。这使论文 §6.5 分桶表所依据的 E3「自报标签」口径过期 ⇒ 追加本节更正。

### 106.1 旧 E3 → 新 E3（关键差异）

| 项 | §104/§105 时的 E3 | 重生成后的 E3（09:54:53） |
|---|---|---|
| `E3_refusal_grid_points.csv` | sha256 `7867df3953d0662135f657336452f6388f8d7748c202bb46ae651133624b56db`（§103 登记值）；自报标签含 `n2_out_of_domain` **102** | sha256 **`0248bd74ee912d9c968b27d5de68ac0fa3b7678d53f26079d785b8170871dec0`**（33,291 B / 476 行）：`mode_or_reason` = **`layer_does_not_exist` 102 ＋ `x_outside_layer_range` 51 ＋ `in_layer` 323 = 476** |
| `E3_refusal_screen.json` | 同上口径 | sha256 `ccc5e919b7f31bc02c4fd97e6d0a9cfcad131265c6d8e0cf81cd3fe97245c695`（3,607 B）：`counts.refusal_reasons_as_reported = {"layer_does_not_exist": 102, "x_outside_layer_range": 51}`；`label_collision = {}` |
| `E3_refusal_histogram.csv` | 桶计数自洽 | sha256 `faf6ab9ad5469f843693f5581071655194d2f830377a5924e395696f3c4ec1c0`（298 B）：**半更新、内部不自洽** —— `n2_out_of_domain` 与「实测 `layer_does_not_exist`」两行均 **0**，各桶之和 **374 ≠ 合计 476** |
| `E3_refusal_screen.md` | §2 表与正文一致 | sha256 `ba56f693bfabeb0af6613a8394c0d78a23e5e5f6f2209c872d8221a363250c93`（3,515 B）：§2 表同样半更新（0/51/0/0/323/0，合计仍 476），而 §2 正文仍写「已报出的两项是 …`n2_out_of_domain` **102**」 ⇒ **表与正文互相矛盾** |

⇒ **本轮判定：以逐点 CSV ＋ `E3_refusal_screen.json` 为准**（二者自洽），**不引用** `E3_refusal_histogram.csv` 与该 md 的分桶表；**只登记、不改 `work/runs/`**（本执行者零写入）。

### 106.2 论文 v5 据此新增的 3 处改动（**改动总数 24 → 27**）

| 编号 | 位置 | 改为 |
|---|---|---|
| **Y1** | §6.5 第三条「不是两类之外的独立桶」 | 那 102 条的**真实触发**是结构约束；修复前曾被**标签碰撞**误报为 `n2_out_of_domain`，**该碰撞已按裁决修复** |
| **Y2** | §6.5 **分桶表整块改写** | 桶 = `layer_does_not_exist` **102** ／ `x_outside_layer_range` **51** ／ `n2_out_of_domain` **0** ／ `in_layer` **323** ／ `n2_extrap` **0** ／ 合计 **476**（来源 = 逐点 CSV（含 sha256）＋ JSON）；另加**修复前自报标签的历史事实**与 **⚠️ 证据内部不自洽的如实登记**（374 ≠ 476） |
| **Z** | §6.5 限定段首句与末句 | `自报标签 …` → `**修复前的**自报标签 …（该碰撞**已按裁决修复**，见 ①）`；末句改为「E3 逐点明细与 JSON 已按修复后的代码重生成，本节分桶表以当前自报标签 `layer_does_not_exist` 列出」 |

- **其余 24 处改动与 §104.3 / §104.4 / §104.5 / §105.2 的描述一致，未变**；**八项裁决的落地内容一处未变**（S4 口径 O 收敛、U3 点名、Q 按批、v2 纳入带标志、405 维持不展开、跨管线只登记、防泄漏按 ulp 归一化整组切分、分类逻辑已修／隔离仍未读取）。
- **经复核仍未变的引用数字**：E2（C `2.7481/3.6648/4.6123` n=1523；A `2.8257/3.9433/4.5822` n=154；池化 `3.686084` n=1677）、E6（删失 `92`/36.8%、截断 `103`/41.2%、`Q=nan` `39`（可用内 `38`）、Q 可判定 `108`、达标 `40`）、E7（净可用 `46`、Q 达标 `11`、分母 `32`）、E8（`446 = 162 + 224 + 60`、`83` vs `117`）。

### 106.3 最终登记值（**取代 §104.2 / §105.3 的对应项**）

| 对象 | 最终值 |
|---|---|
| 论文 v5 `docs/PMUT_DAC2027_初稿_v5_20261009.md` | **`2daf0cdf7340014475c1af4fc9f85f1ad6d17c9e9f871a24af2b0b81f86dcf27`（74,416 B / 627 行 / 纯 CRLF；27 处外科式改动）** |
| 改动说明 `docs/PAPER_REVISION_LOG_20261009.md` | `da2365f74f35ebd77e14a62dacbda710f497af063de007c675efcc394d077b8f`（84,329 B / 434 行；含 §L、§L.5、§L.6） |
| 索引 `docs/INDEX-records-and-rulings.md` | §106 追加后的值**不写进文件**（避免哈希自指）；追加器输出原文见交付说明 |
| v4（基线，**未改**） | `4472aa5b7e86528d2bc05d6f68c284cc45bc96b9eb1ec29b674c4e48374dce55`（**追加本节后复算仍逐位一致**） |
| v3 / v2（**未改**） | `76e274a8924f237891839312d00a104b9e4dd2df8aad01cb63d81d6f7bdda94c` / `329b3f942a5e54c6db99203c2fd5566e4f5b7c5e89806b2929ea23fc1db6e5e3` |

- **代码/测试状态（交付时实测）**：`src/memsharness/multichannel_surrogate.py` = `7ec83d3d83c58004aaa1a9f6fbf0d70ed9bd3e1b67c89db3c581665a0d063ff4`（21,526 B）；`tests/test_mc_refusal_classification.py` = `a33cadfdfd5bb6c60bd3881917f6cdad141756b865c091fc300ec29c1a60819a`（8,057 B）；该用例本轮以**只读**方式实跑 ⇒ **9 passed**。**全量 pytest 未跑**。
- **未提升任何状态**：`solver_spec.json` 仍 **`state = draft`**、sha256 `21315173fd2732c7384c4a3d437bb7f7c297d5c3047b5ff01094ca3553b6bd3f`；`multichannel_model.json` 仍 **`status = draft`**、sha256 `0d872fb14bb9093a1a486327e3e24298af81290e58756ed9a70b8b2b3ef444b1`。
- **说明**：若其他执行者**再次**改动 `src/` 或 `paper-evidence` 包，本行登记值即随之过期；**以交付说明中的最后一次实测为准，本执行者不再追改**。**本执行者零写入 `src/`、`tests/`、`work/runs/`；未跑 COMSOL；未编造数字；未把「已裁定」写成「已完成」**（分类碰撞＝**已完成**、隔离读取＝**另议且仍未生效**，二者在论文中分别如实表述）。
