# 致 Codex：LT0 开工回报（含一项环境级 pytest 回归与能力自验证数据）

> 回应：`TO_DEEPSEEK_HARNESS_LT0-LT3执行工单.md`（我方存档 `docs/TO_CODEX_order-20260913-LT0-LT3.md`，sha256 `98715e41…`）
> 日期：2026-09-13/14｜**授权范围内只执行 LT0**；LT1–LT3 未启动
> 证据标记：`[实测]` / `[静态可复核]` / `[待核实]` / `[推断]`

---

## 1. 阶段回报（按你 §7 的字段格式）

```text
phase              = LT0
status             = RUNNING
start_time         = 2026-09-13（本机时间）
completed_units    = LT0-A ✅｜LT0-D(部分) ⚠️｜LT0-B/C 🔄 运行中
expected_units     = LT0-A/B/C/D/E + 验收门槛
model_sha256       = cbe9ccc18e51005f6aa147e8d7fdd5df62266c5f9117d9829888336f326582d9
script_sha256      = work/tools/lt0_audit.py（本轮新建，单 client 版）
criteria_hash      = 待 B/C 完成后写入 lt0_audit.json
failed_units       = LT0-D 的 pytest 回归（见 §3）
retry_count        = 0
server_cleanup     = 由 lt0_audit.py 的 try/finally + 30 s 端口探测负责（进行中）
next_phase_eligible = 待 LT0 门槛全部判定
blocking_reason    = pytest_regression = false（环境级，见 §3）
```

---

## 2. LT0-A：Circuit 停用证据 ✅（**api_readback 路线成立**）

重载模型 `work/models/b_GE_task3_2new_reverse_voltage_drive_v1.mph` 后读回 `[实测]`：

```text
physics("cir").isActive()  = false          ← 停用成立
physics tags               = [acpr, solid, es, cir]   ← 接口保留（未删除，便于回退）
```

⇒ **`cir_inactive_verified = true`**，`cir_inactive_evidence = api_readback`。

**同时如实报告三条未成功的旁证路线**（不隐去）：
| 路线 | 结果 |
|---|---|
| 求解器自由度签名（`sol1.s1.i1.mg2.hybridvar`） | `FlException: 属性"hybridvar"无法转换`（该属性是**字符串数组**，我按字符串读取，类型不匹配） |
| Study 步物理场参与列表（`std1.freq.phys`） | `FlException: 未知属性`（该属性名在本版本不存在） |
| 导出 `.m` 静态文本 grep `active(false)` | `m_export_ok = false`（COMSOL Java 的 `model.save("*.m")` 未产出文本文件） |

⇒ 目前**只有 API 读回这一条证据**。若你要求"api_readback 不足，须补求解器签名"，我会改用
`getStringArray`/`getStringMatrix` 读 `hybridvar`，并改从 `java.sol("sol1").feature("s1").feature("i1")
.feature("mg2").getStringArray("hybridvar")` 逐个元素检查是否含 `cir.`/`term1`。

---

## 3. LT0-D：`pytest` 回归 **未通过** —— 环境级故障，非项目代码

```text
ERROR tests/test_ml_pipeline.py / tests/test_pod.py（采集期）
ImportError: DLL load failed while importing _radius_neighbors:
             应用程序无法启动，因为并行配置不正确（Windows SxS）
```

- **根因** `[实测]`：`sklearn.metrics` 的原生扩展 DLL 加载失败（SxS 并行配置错误）。追踪栈中
  `importlib` 来自 `..\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\…`
  ⇒ 本 venv 的**基础解释器是一个缓存运行时**；这类缓存的 Python 被刷新/移动后，
  按旧解释器编译的 sklearn 扩展即以此方式失败。
- **影响面** `[实测]`：仅 `memsharness.ml`（代理模型 / POD 两个测试模块）；
  **COMSOL 链路不受影响**（`duckdb` / `pandas` / `numpy` / `mph` 全部正常，预检、求解、聚合照跑）。
- **修复路径**：`pip install --force-reinstall scikit-learn`（按当前解释器重装扩展），
  但**当前清华镜像 SSL 断连**（此前已实测），暂时装不上。
- 按你工单的口径，我把 `pytest_regression` 记为 **false**，并把它列为 LT0 的**唯一阻塞项**。

**请你裁定**：该环境级 ML 支线故障是否**阻止 LT1**？我方理解 LT1–LT3 只依赖 COMSOL 链路与
`work/tools/` 下的脚本，与 sklearn 无关；若你同意"带条件放行"，我将在报告里持续标注
`pytest_regression = false（仅 ml 支线，环境级）`。若你要求先修复，我需要在镜像恢复后重装 sklearn。

---

## 4. 能力自验证数据（你之前要求的"自算数据"）

按指令**不读取用户导出表**，用 COMSOL 6.4 自算 `x_scale = 0.6 / 0.7`（`N_w_te1 = 4`，legacy 驱动=你那张表的同款工况），
3 频点、**表内每个变量都算** `[实测]`（`work\runs\xscale-0607-3f\selfcomputed_xscale_legacy.csv`）：

| x_scale | 频率 | Zin1_R (Ω) | Zin1_X (Ω) | Zin2_R/X | Ptot (W) | V_center (实, 虚) | Vave (m/s) | 单元数 |
|---:|---:|---:|---:|---|---:|---|---:|---:|
| 0.6 | 5 MHz | −3.813697 | 6752.499 | =Zin1 | 4.437298e-08 | (−7.916994e-04, −4.138560e-02) | 0.008871414 | 136,250 |
| 0.6 | 20 MHz | −22.752861 | 1745.251800 | =Zin1 | 3.996822e-06 | (−5.760262e-02, 1.705364e-02) | 0.029835303 | 136,250 |
| 0.6 | 35 MHz | −11.425466 | 993.679023 | =Zin1 | 6.184073e-06 | (−7.472185e-02, 2.001931e-02) | 0.015603979 | 136,250 |
| 0.7 | 5 MHz | −9.262223 | 5769.322966 | =Zin1 | 1.467017e-07 | (−2.639415e-03, −5.893050e-02) | 0.013868324 | 149,485 |
| 0.7 | 20 MHz | −13.536173 | 1491.663046 | =Zin1 | 3.224849e-06 | (−4.401162e-02, −1.149680e-02) | 0.025421435 | 149,485 |
| 0.7 | 35 MHz | −9.184913 | 847.873329 | =Zin1 | 6.774528e-06 | (−6.908358e-02, −2.650638e-02) | 0.021887469 | 149,485 |

- **交叉验证** `[实测]`：20 MHz 的 `Ptot = 3.996822405306258e-06`、`Vave = 0.02983530` 与早先 M1 端口审计**逐位一致**；
  `Zin1` 模 `1745.40 Ω` 一致 ⇒ 两条独立通路互证，且 `Zin2 ≡ Zin1` 再次逐位确认（复制错误）。
- 该数据同时满足 **LT0-E 的 `x_scale` 一行**：包围盒 x 半宽比 **1.166667 = 0.7/0.6（精确）**、y/z 不变、
  单元数 136,250 → 149,485（+9.7%）⇒ 几何与网格的下游传导均已证。

### 4.1 一次失败与修复（方法论）

反向分支在同一次脚本里**未跑成**：我原先**每个分支新建一个 `mph.Client`**，而 MPh 规定
**每个 Python 会话只能有一个 client**，`disconnect()` 后再建会报 `Not connected to a server`。
⇒ 已在 `lt0_audit.py` 中改为**全程单 client**（分支/步骤间只做 `clear()`，不 `disconnect`）。`[实测]`

---

## 5. LT0–LT3 已登记为本轮执行计划

已建立 10 项执行清单并锁定口径：LT0-A/B/C/D/E + 验收 → LT1（5 组合×3 频点 = 15 点）→
LT2（72 组合×7 频点 = 504 行，8–16 组/批、独立 server、逐组合 checkpoint、2.5 GB 停止线）→
LT3（质检、分列指标、Pareto、候选重选、legacy 归一化对照）→ **强制 STOP 并提交总报告**（`PASS_WAITING_REVIEW`）。
工单禁止项已确认遵守：**不**改 `fmax=45 MHz` 生产网格、**不**做精扫/桥接/7R/代理模型/阵列外推。

---

## 6. 请你裁定

1. **LT0-A 证据强度**：`api_readback`（`isActive() = false`）是否足够？若不足，我按 §2 的
   `getStringArray("hybridvar")` 路线补求解器签名证据。
2. **`pytest_regression = false` 是否阻止 LT1**（我方判断：仅 ml 支线、环境级、与 COMSOL 链路无关）？
3. LT0-B/C 完成（预计数分钟）后是否**自动进入 LT1**，还是先停下等你复核 LT0？

**当前环境**：LT0 审计正在进行（3 频点求解中）；跑完后端口按 30 s 探测规则确认关闭，无残留 server。
