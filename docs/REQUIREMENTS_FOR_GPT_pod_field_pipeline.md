# 需求书：把 PMUT 场级快照做成"公共点集 → 掩膜 → POD → 留一验证"的管线（给 GPT 实施）

> **这份文件是自包含的**：实施者看不到提出方的历史对话。所有数字都是**实测**的，出处写在括号里或紧随其后。
> 任务性质：写一个**可复现的 Python 脚本**，把已经存在的场级导出（`.mat`）对齐到**一套显式公共点集**，
> 建 POD 降阶模型，并做**留一**精度评估，产出**机器可读的报告 JSON**。
> 语言/环境：Python 3.12 + numpy + scipy（本地 Windows）；数据在**远端 Linux**，**只读**。

---

## 1 数据在哪（只读！不许写远端）

```
远端主机（ssh 别名，已配好密钥）：ubuntu-10-180-7-46
数据根目录（只读）：
  /home/lab/projAI4US/autodesign/exported_results/te2_8_pod_fields_20MHz_v1/
      ├── pod_20MHz/          567 个 .mat（主数据：x 网格 × N1，固定 20 MHz）
      ├── representative_full/ 5 个 .mat（x0.95_N06 在 f=5.0/5.5/6.0/6.5/7.0 MHz 的"全量场"）
      └── snapshot_index.tsv   权威清单（572 行数据 + 1 行表头）
```

取文件只用 `scp`（**不要**在远端跑任何写入、不要建临时文件）：

```powershell
scp -o BatchMode=yes ubuntu-10-180-7-46:"<远端路径>" "<本地目标>"
```

已实测的取文件命令形态（PowerShell）：
`scp -o BatchMode=yes -o ConnectTimeout=20 ubuntu-10-180-7-46:/home/.../pod_20MHz/x0.20_N01_f20MHz.mat .`

> ⚠️ 若要用 `ssh host bash -s < file` 的方式喂脚本：**必须把本地脚本存成 LF 换行**
> （实测：带 CR 会报错；可靠姿势是 `cmd /c "ssh … bash -s < file"`）。

## 2 `.mat` 的真实格式（实测，别猜）

* **Matlab v5，不是 v7.3/HDF5** ⇒ 用 `scipy.io.loadmat` 读（远端 python3 **没有** numpy/scipy/h5py，所以**只能在本地解析**）。
* 单个文件示例 `pod_20MHz/x0.20_N01_f20MHz.mat`：842,723 B。

变量表（实测，`x0.20_N01_f20MHz.mat`）：

| 变量 | 形状 | dtype | 含义 |
|---|---|---|---|
| `x_m` / `y_m` / `z_m` | `[1, N]` | float64 | **每个快照自带的三维坐标**（单位 m） |
| `p_total_Pa` | `[1, N]` | **complex128** | **复声压场**（这就是要建模的场） |
| `p_finite_mask` | `[1, N]` | uint8 | **导出方给的有限性掩膜**（1 = 该点有限） |
| `freq_Hz`, `x_scale`, `N_w_te1`, `N_w_te2`, `outer_solnum` | `[1,1]` | — | 元数据 |

`N` **逐文件不同**（见 §3），所以**不能假设各快照点对点对应**。

## 3 清单与数据规模（实测，来自 `snapshot_index.tsv`）

列：`kind, status, x_scale, N_w_te1, N_w_te2, freq_Hz, outer_solnum, inner_solnum, x_holdout_role, n_holdout_role, file, n_points`

| 项 | 实测 |
|---|---|
| 数据行 | **572** |
| `kind` | `pod20` **567**、`representative_full` **5** |
| `status` | `completed` 571、`skipped_existing` 1 |
| `x_scale` | **0.20 … 1.00，步长 0.01（81 个值）** |
| `N_w_te1` | **1 … 7** |
| `N_w_te2` | **8（唯一）** |
| `freq_Hz` | 20 MHz（`representative_full` 另有 5.0/5.5/6.0/6.5/7.0 MHz） |
| `n_points` | 572 个快照：**min 60,064 / p50 110,483 / max 617,756 / 合计 72,577,560** |
| **导出方已切分** | `x_holdout_role`: train 532 / holdout 35 / na 5；`n_holdout_role`: train 405 / holdout 162 / na 5 |

**硬约束**：`*_holdout_role` 是**数据提供方给的切分**，实施时**必须沿用**，
**禁止**自行重新切分（否则等于把留出集二次利用，属于不可原谅的口径问题）。

## 4 上一次尝试与它为什么失败（**这是本次要修的核心**）

上一次的做法与结果（实测）：

* 做法：取**点数最少**的快照（`x0.20_N01`，N=60,064）的坐标当"公共点集"，
  其余快照用 **KDTree 最近邻 + 容差 1e-9 m** 映射到这套点上；
* 结果：**公共掩膜只剩 1,187 / 60,064 = 2.0%**；POD 首模能量 0.9967（无意义）；
  留一 rel_L2 = 0.171 / 0.066 / 0.090 / 0.048 / 0.025 / 0.012 / 0.043（max 0.171，median 0.048）。

**失败原因（已定位，不是数据问题，是方法问题）**：
`x_scale` 固定、`N_w_te1` 变化时**几何会变 ⇒ 网格会重划**，所以各快照点数从 6 万到 62 万不等，
点与点**不对应**。用"拿一个快照的网格 + 最近邻硬映射"必然只对齐极小一部分。
⇒ **必须改成"显式公共点集 + 插值"**（这正是 `field-io-contract` 的要求）。

## 5 要实施的正确方法（逐步，可验收）

1. **定义显式公共点集**：产出一个**固定的点集规格 + 坐标文件**（例如规则网格，或按数据包围盒定的柱坐标网格）。
   规格写成 `{"spec": {每轴 start/stop/n}, "points_file": "<相对路径>"}`，
   坐标文件一行一个点（`x y z`，单位 m）。**点集一旦定下就冻结**（写进报告与哈希）。
2. **逐快照插值到公共点集**：用 `scipy.interpolate.griddata`（推荐 `method="linear"`，并同时算一个
   `method="nearest"` 的诊断量）；**复数场要拆实部/虚部分别插值**（`griddata` 不支持复数），再合成复数。
   域外点**必须产生 NaN**（`griddata` 默认 `fill_value=nan`，要显式传，别让它填 0）。
3. **公共掩膜** = 在**所有**参与快照上都"插值成功且有限"的点：
   `common = AND_i (isfinite(p_i) & p_finite_mask_i_插值后)`。
   **绝不允许把 NaN 当 0 填充**（那会污染 POD 基与所有误差）。
4. **POD**：只在公共掩膜点上做；先减均值，再 SVD；报告**能量占比累积**与达到 99.9% 所需模数。
   正定量（如声压幅值）建议在 `log10` 空间也报一份对照（可选）。
5. **留一（LOO）验证**：**逐个快照**留出 → 用其余快照重新拟 POD 与系数映射 → 重构被留出的场 →
   算 `rel_L2 = ‖pred−true‖₂ / ‖true‖₂`（**只在公共掩膜点上、双方都有限**）。
   **必须报 `max`**（不许用平均值掩盖最差点），同时报 median 供参考。
6. **回写报告 JSON**（字段见 §6），并把所有下载文件的 **sha256** 记录进去。

## 6 交付物

### 6.1 脚本（1 个入口即可）
`pipeline_pod_fields.py`，命令行参数至少：
`--remote-host`、`--remote-dir`、`--local-dir`、`--which`（`train` / `all` / 显式文件列表）、
`--grid`（点集分辨率）、`--tol`、`--out`。

### 6.2 报告 JSON（字段必须齐，缺失就写 `null` 并**在 errors 里说明原因**）

```json
{
  "kind": "pod_field_pipeline",
  "generated_at": "...",
  "remote_dir": "...", "local_dir": "...",
  "files": [{"name": "...", "bytes": 0, "sha256": "...", "n1": 1, "x_scale": 0.2, "freq_Hz": 20000000,
             "split_x": "train", "split_n": "train", "n_points": 60064}],
  "point_set": {"spec": {...}, "points_file": "...", "sha256_points_file": "...", "n_points": 0, "origin": "how it was chosen"},
  "interpolation": {"method": "linear", "n_interp": 0, "per_snapshot": [{"name": "...", "seconds": 0.0, "n_finite_after": 0}]},
  "common_mask": {"n_points": 0, "frac_of_point_set": 0.0, "n_snapshots": 0},
  "pod": {"n_modes_999": 0, "energy_first5": [0.0], "singular_values_head": [0.0]},
  "loo": [{"held_out": "...", "k_modes": 0, "rel_L2": 0.0}],
  "loo_max_rel_L2": 0.0, "loo_median_rel_L2": 0.0,
  "verdict": "pipeline_ok | alignment_failed | inconclusive",
  "caveats": ["每一条都要明说没做什么"],
  "errors": ["每条失败原因（不要吞掉异常）"]
}
```

### 6.3 不许做的事（红线）

* 不许写远端任何文件；
* 不许自行重新切分 train/holdout（沿用 `snapshot_index.tsv` 的 role 列）；
* 不许在公共掩膜之外统计 POD 或误差；不许把 NaN 当 0；
* 不许用"平均误差"代替 `max`；不许在掩膜率很低时仍给出精度结论；
* 不许把复数场先转成实数（会丢虚部——实测过一次：`max|Re(p)|` 比真正的 `max|p|` 低 2.5%–15%）；
* 不许声称"已验证等价于 COMSOL"或给出工程绝对值；本管线只是**降阶 + 留一自检**。

## 7 验收判据（不满足就如实报，不许放宽）

| 项 | 判据 |
|---|---|
| 对齐是否成功 | **公共掩膜 ≥ 80%**（即在公共点集上，至少 80% 的点在所有参与快照上都插值成功且有限） |
| 插值诊断 | 每个快照报插值耗时与"插值后有限点比例"；若有 `nearest` 与 `linear` 的差异，两张都报 |
| POD | 报能量累积；达到 99.9% 所需模数 |
| 留一 | 报 `rel_L2` 的 **max** 与 median；**max 与 median 差距过大时必须点出**（不许只报 median） |
| 可复现 | 报告里每个数字都能从 `files[].sha256` + 参数重算 |

**掩膜 < 80% 时的正确结论是**：`verdict = alignment_failed`，并给出**诊断**（是点集选得不合适、
还是几何变化超出插值适用范围、还是 `p_finite_mask` 覆盖不足），**不要**继续给 POD 精度。

## 8 已知的坑（都是实测踩过的）

1. **复数不能直接插值/转 float**：`griddata` 只吃实数；`np.asarray(x, dtype=float)` 会**静默丢虚部**（numpy 只给一条 `ComplexWarning`）。
2. **点数逐文件不同**（60,064 … 617,756）：任何"逐点对齐"的假设都是错的。
3. **内存尺度**：单个最大快照 617,756 点；`griddata` 是 Delaunay 三角化，**3D 插值在 10^5–10^6 点量级会非常吃内存与时间**。
   若超时/爆内存，允许的替代是：**降维到轴对称/柱坐标 2D 插值**（若数据确实轴对称）或**先把公共点集降密**，
   但**必须实测并报告**实际耗时与内存，不许静默降级。
4. **Windows 路径与转义**：Python 字符串里的 `\p`、`\S` 等会触发 `SyntaxWarning`，用原始串或双反斜杠。
5. **ssh 喂脚本的 CR 问题**：见 §1 的提示。
6. **远端 python 缺 numpy/scipy/h5py**：解析一律在本地做。

## 9 复现入口（当前已有、可参考或直接改造）

* 已存在的小规模尝试（**方法错，但流程与报告结构可复用**）：
  `scripts/pipeline_smoke_x020.py` → 报告 `work/runs/te2_8_pod_fields_20261005/pipeline_smoke_x020.json`
* 已取回的清单与单文件（用于核对格式）：
  `work/runs/te2_8_pod_fields_20261005/snapshot_index.tsv`（sha256 见报告）、
  `work/runs/te2_8_pod_fields_20261005/x0.20_N01_f20MHz.mat`
* 先做**小规模**：只用 `x_scale=0.20` 的 7 个快照（`x0.20_N01..N07_f20MHz.mat`，共约 6 MB）跑通全流程，
  **再**扩到 train 子集（405 个，约 700 MB）；**最后**才全量（572 个，998 MB）。

## 10 一句话总结要 GPT 做什么

> 写一个脚本：从 `ubuntu-10-180-7-46` 只读取回 `te2_8_pod_fields_20MHz_v1` 里的 `.mat` 快照，
> 定义一套**显式公共点集**并用 `scipy.interpolate.griddata`（复数拆实虚部）把每个快照插值上去，
> 取**所有快照都有限**的点作公共掩膜，在掩膜上做 POD 与**留一** `rel_L2`（**报 max**），
> 产出上面字段齐全的报告 JSON；**掩膜率 < 80% 就如实判 alignment_failed 并给诊断，不要给精度结论**。
