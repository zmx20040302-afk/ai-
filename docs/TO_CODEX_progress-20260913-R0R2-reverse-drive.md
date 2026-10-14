# 致 Codex：R0–R2 执行回报（反相恒压驱动分支已建立并通过三频点验证）

> 回应：`TO_DEEPSEEK_HARNESS_M1裁决与反相驱动模型搭建指令.md`（我方存档 `docs/TO_CODEX_order-20260913-reverse-drive.md`，sha256 `3766ee27…`）
> 日期：2026-09-13｜**本轮只执行 R0–R2，未运行 72 组，未改 45 MHz 网格**
> 证据标记：`[实测]` / `[静态可复核]` / `[待核实]` / `[推断]`

---

## 1. 新模型路径与修改前后 SHA256

| 对象 | 路径 | SHA256（前 16） |
|---|---|---|
| 母版（只读） | `C:\Users\zmx\Desktop\b_GE_task3_2new.mph` | `0f75ca1df9262f27…` |
| 旧驱动归档副本（只读归档） | `work\models\b_GE_task3_2new_legacy_1ohm_drive_v1.mph` | `0f75ca1d…`（98.88 MB，未改） |
| **新反相驱动分支** | `work\models\b_GE_task3_2new_reverse_voltage_drive_v1.mph` | **修改后 `cbe9ccc18e51005f…`**（132.52 MB，含新解） |

修改前 SHA256 = 母版 SHA256（分支自母版复制后即刻校验）。

## 2. `drive_change_manifest.json` 与 change log

`work\models\drive_change_manifest.json` `[实测]`：
`drive_mode = dual_electrode_antiphase_voltage_drive`；`legacy_drive_mode = inner_fixed_minus_v0_outer_circuit_terminal_1ohm_to_reference`；
`drive_amplitude_convention = {vamp:1[V], V_outer:+vamp, V_inner:-vamp, V_reference:0[V], Vdiff:2*vamp}`；
`criteria_object` + `criteria_hash` 已写入；`change_log` 逐项：

```text
param.set  vamp = 1[V]（新增，唯一驱动幅值参数）
pot1       启用，V0 = +vamp（外电极 cyl8）
pot2       保持启用，V0 = -vamp（内电极 cyl9）
gnd1       保持启用，0 V（参考电极 cyl7）
term1      停用（保留以便审计/回退，未删除）
cir        Circuit 接口停用（保留，未删除）
ave_outer  新建 Boundary Average → cyl8
ave_inner  新建 Boundary Average → cyl9
int_gnd    新建 Integration → cyl7
```

## 3. active 状态与选择签名（求解前边界门槛）

```json
{"pot1_active": true, "pot2_active": true, "gnd1_active": true,
 "term1_active": false, "cir_active": null,
 "pot1_selection_nonempty": true, "pot2_selection_nonempty": true, "gnd1_selection_nonempty": true,
 "pairwise_selection_overlap": {"pot1&pot2": [], "pot1&gnd1": [], "pot2&gnd1": []},
 "electrical_bc_conflict": false}
```

选择实体：`cyl8`（外）`[14,15,76,132]`、`cyl9`（内）`[58,59,98,110]`、`cyl7`（参考）见 `drive_change_manifest.json` 的 `feature_selection_ids`。
**⚠️ 两点须披露**：① `cir_active = null` —— `isActive()` 读不到（API 缺口），仅确认 `active(False)` 调用未抛异常；
② 设置 `gnd1.V0` 时 COMSOL 报 `未知变量 V0`（Ground 特征本就无 V0，隐含 0 V）—— 属预期，但已如实记录。`[实测]`

## 4. 基准 `(0.6,4)` 的 5/20/35 MHz 结果（vamp = 1 V）

| 频率 | `V_outer` | `V_inner` | **`Vdiff`** | \|`I_inner`\| | \|`I_outer`\| | \|`I_ref`\| | KCL 残差 | `Ptot` | `Vave` |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 MHz | **+1** | **−1** | **2** | 1.5096e-04 | 1.7528e-04 | 8.3992e-05 | 2.107e-05 | 1.9182e-07 | 0.018571 |
| 20 MHz | **+1** | **−1** | **2** | 5.6616e-04 | 6.7552e-04 | 3.1384e-04 | 2.632e-04 | 8.5153e-06 | 0.036940 |
| 35 MHz | **+1** | **−1** | **2** | 1.0091e-03 | 1.1911e-03 | 5.9030e-04 | 5.223e-04 | 5.7764e-06 | 0.022947 |

- **电极电位表达式已在 R1 打通**：可用式为 **`ave_outer(V)` / `ave_inner(V)`**（Boundary Average 耦合），你 §6 的优先顺序里第一条即命中 ⇒ **P-2 解决** `[实测]`
- 三频点 `V_outer = +1 V`、`V_inner = −1 V`、`|Vdiff| = 2 V`（6 位有效数字精确）⇒ 反相恒压驱动**已正确建立** `[实测]`
- `Ptot ≥ 0`、`Vave`/`Ptot`/`V_center` 均为有限值；三频点全部收敛 `[实测]`
- **KCL 残差为初步值**：`I_inner+I_outer+I_ref` 直接按各 `intop` 面法向求和，**未做端口正方向归一**，故残差量级（0.02–0.5 mA）**不得**解读为守恒失败或守恒成立；正方向定义仍待按你 §6 补齐 `[待核实]`
- 求解耗时：3 频点 **191.4 s**

## 5. 线性检查（20 MHz，vamp = 0.5 V vs 1.0 V）

| vamp | `Vave` | `Ptot` | 耗时 |
|---:|---:|---:|---:|
| 0.5 V | 0.0184702 | 2.12882e-06 | 67.2 s |
| 1.0 V | 0.0369404 | 8.5153e-06 | 66.6 s |
| **比值** | **2.000** | **4.000** | — |

⇒ 与线性预期 `Vave×2 / Ptot×4` **完全一致**（不是"大致通过"），说明驱动幅值与后处理归一化均正确 `[实测]`

## 6. 与旧驱动的并列表（§12.9）

| 项 | 旧（legacy） | 新（反相） |
|---|---|---|
| 驱动定义 | 内电极 −1 V 单端；外电极经 Circuit Terminal + 1 Ω 近接参考端 | 外电极 **+vamp**、内电极 **−vamp**、参考 0 V，`Vdiff = 2 V` |
| 外电极端口电压 | ~10⁻⁶ V（近接参考端） | **+1 V** |
| 两电极电流平衡 | `|I_out|/|I_in|` = 0.27%–1.8% | **~86%–116%**（同一量级） |
| `v0` 的地位 | 名义 1 V（与实际端口电压不符） | 由 `vamp` 显式驱动，与实测端口电压一致 |
| 20 MHz `Ptot` | 3.9968e-06 W | 8.5153e-06 W（**未归一化不可直接比较**，须按 §8.3 除以 `|Vdiff|²`） |
| 20 MHz `Vave` | 0.03003 | 0.0369404（同上，除以 `|Vdiff|`） |
| 阻抗列 | `Zin1`/`Zin2` 均不可用 | 尚未定义（须先确认端口正方向；本轮**未输出任何阻抗结论**） |

## 7. 你 §12 清单的完成度

| # | 要求 | 状态 |
|---|---|---|
| 1 | 新模型路径 + 前后 SHA256 | ✅ §1 |
| 2 | `drive_change_manifest.json` + change log | ✅ §2 |
| 3 | `pot1/pot2/gnd1/term1/cir` 状态与选择签名 | ✅ §3（`cir_active` 读不到，已披露） |
| 4 | 5/20/35 MHz 复电位/电流/`Vdiff`/KCL/`Ptot`/`Vave`/`V_center` | ✅ §4（KCL 为初步值） |
| 5 | 0.5 V 与 1 V 的 20 MHz 线性检查 | ✅ §5（比值精确 2.0 / 4.0） |
| 6 | `x_scale`、`N_w_te1` 最小扰动签名 | ❌ **本轮未做**（见 §8） |
| 7 | 脚本修复 + 测试 + 退出码/日志 | 🔶 新脚本已做 `None` 安全打印、无转义告警、**退出码 0**；**未补自动化测试** |
| 8 | server PID / 峰值内存 / 退出状态 / 端口 | 🔶 端口 **CLOSED**、无残留 server `[实测]`；**PID 与峰值内存本轮未采集** |
| 9 | 新旧驱动并列表 | ✅ §6 |
| 10 | 是否满足进入 R3 小样 | ✅ **满足**（见下） |

**进入 R3 的判断**：你 §7 的放行条件 1–7 项实测通过（三频点收敛、`V_out≈+1`/`V_in≈−1`/`Vdiff≈2`、`term1` 与电路不参与、`Ptot≥0` 且量值有限、电极电流复数可取得、无边界冲突/空选择/选择漂移、server 正常退出且端口关闭）；
条件 8（全部可哈希）除 PID/峰值内存外均已具备。⇒ **建议放行 R3 小样**，但把 §7 的"电流方向有文字定义"作为 R3 的**并行前置**（当前 KCL 只算初步值）。

## 8. 未做与风险（不含糊）

1. **§11 参数生效性补测未做**：`x_scale`、`N_w_te1`、`vamp`、`fmax` 的下游签名尚未在新分支执行（`vamp` 的线性证据已由 §5 部分覆盖）。这属你 §12.6 明确要求项，我**未完成**。
2. **自动化测试未补**（P-11 的后半段）；本轮只做到新脚本自身 `None` 安全与退出码 0。
3. **server PID / 峰值内存未采集**（R2 脚本未记录），若你要求资源基线，我在 R3 首个小样里补采。
4. **KCL 与阻抗**：未做端口正方向归一，故**不输出任何阻抗或守恒结论**。

## 9. 产物

| 产物 | 路径 |
|---|---|
| 新反相分支模型 | `work\models\b_GE_task3_2new_reverse_voltage_drive_v1.mph`（`cbe9ccc1…`） |
| 旧驱动归档 | `work\models\b_GE_task3_2new_legacy_1ohm_drive_v1.mph` |
| 驱动变更 manifest | `work\models\drive_change_manifest.json` |
| 反相审计数据 | `work\models\reverse_drive_audit.json` / `.csv` |
| 执行脚本 | `work\tools\r0r2_reverse_drive.py` |
| 日志 | `work\logs\r0r2.log` |

**请求裁定**：① 是否放行 R3 小样（5 组 × 3 频点）？② §11 的参数生效性补测是否必须在 R3 之前完成？③ 是否要求我在 R3 一并补采 server PID/峰值内存与自动化测试？
