# 致 DeepSeek Harness：MEMS MCP 注册与生产可用性审核回复

> 日期：2026-09-14  
> 审核对象：`docs/dsh_mcp_registration.md` 及本机实际 profile、overlay、MCP server、COMSOL queue 代码  
> 审核结论：**注册结构通过；当前端到端自测失败；尚不具备执行 PMUT LT0–LT3 长任务的生产能力**

## 0. 结论先行

### 已通过

1. `C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml` 的 `insert:` 结构正确。
2. GUI profile 中 Python、cwd、`serverName=mems`、stdio、60秒超时均指向当前 C 盘仓库。
3. `verify_mems_install.py` 结构校验通过。
4. MCP server 实际注册了11个工具：

```text
data_stats, env_report, module_capability, ping, records, run_trace,
sim_cancel, sim_logs, sim_status, sim_submit, sim_templates
```

5. 项目技能实际为 **9个**，不是文档中的8个；新增的 `sweep-analysis` 已存在。

### 未通过

1. `python -m memsharness.mcp_server --selftest` 当前退出失败：`ping` 以读写模式打开 DuckDB，在受限环境或数据库被占用时直接抛异常。
2. `work/mcp-overlay.patch.yml` 仍写旧路径 `D:\桌面\memsharness`，当前 headless验证命令不可用。
3. `sim_templates` 目前只有二维热板和悬臂梁示例，没有 PMUT 反相驱动模板；`sim_submit` 无法提交本项目LT0–LT3。
4. `sim_submit` 只写入队列，不会启动worker；文档没有给出已持续运行、可监督的worker服务。因此“提交后轮询”目前只有前半段。
5. `sim_cancel(force_kill=True)` 默认强杀进程树，且 `run_id` 未做格式/路径验证、PID未做进程身份复核，不适合直接暴露给智能体。

### 当前授权

```text
MCP registration status = CONDITIONAL_FAIL
MCP read-only monitoring = 修复并复验后可用
MCP PMUT solve submission = 禁止
MCP force cancellation = 禁止
LT0–LT3 execution = 继续使用已审核的本地脚本/批处理流程
```

不要因为工具出现在DSH会话中，就宣布“MCP集成完成”或通过它提交当前504点粗扫。

## 1. 现场复核结果

### 1.1 GUI profile配置正确

实际条目为：

```yaml
- insert:
    - id: mcp-mems-harness
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: mems
        transport: stdio
        command: 'C:\Users\zmx\Desktop\memsharness\work\.venv\Scripts\python.exe'
        args: ['-m', 'memsharness.mcp_server']
        cwd: 'C:\Users\zmx\Desktop\memsharness'
        toolCallTimeoutMs: 60000
        failOnStartupError: false
        reconnect:
          enabled: true
```

这一部分结构可接受。`failOnStartupError:false` 只表示MCP故障不会拖垮GUI，不代表MCP健康；GUI启动成功不能作为MCP验收证据。

### 1.2 headless overlay路径错误

实际 `work/mcp-overlay.patch.yml` 仍为：

```text
command = D:\桌面\memsharness\work\.venv\Scripts\python.exe
cwd     = D:\桌面\memsharness
```

当前机器仓库位于 `C:\Users\zmx\Desktop\memsharness`。必须由安装脚本基于 `repo_root()`重新生成overlay，禁止在文档和脚本中保留旧机绝对路径。

### 1.3 selftest实际失败

工具枚举成功，但调用 `ping` 时失败：

```text
IOException: Cannot open ... work/store/mems.duckdb: 拒绝访问
```

根因之一是 `ping()` 和 `data_stats()` 都调用默认的 `connect()`，默认 `read_only=False`。这与文档把它们称为“只读工具”不一致，也会增加与队列worker争用DuckDB单写者的风险。

## 2. 阻塞级问题与修复要求

### P0-1：把基础健康检查与数据库解耦

`ping` 不应因为数据库被锁、只读权限或数据库暂不可用而使整个MCP自测失败。建议返回分层状态：

```json
{
  "ok": true,
  "tool": "mems-harness",
  "version": "...",
  "mcp_server_ok": true,
  "store_ok": false,
  "store_tables": null,
  "store_error": "..."
}
```

要求：

- `ping`本身不写数据库；
- 数据库统计使用 `connect(read_only=True)`；
- 数据库不可用时返回结构化降级状态，不抛出导致selftest退出的未处理异常；
- `data_stats`同样使用只读连接，并返回明确的 `store_unavailable`；
- `records/run_trace`保持只读连接；
- 写数据库只出现在明确的提交/入库路径中。

### P0-2：修复当前机器的headless overlay

重新生成：

```text
C:\Users\zmx\Desktop\memsharness\work\mcp-overlay.patch.yml
```

要求：

- command/cwd来自运行时仓库根，不手工写固定盘符；
- `failOnStartupError:true` 保留在headless验收层，以便失败时非零退出；
- 加入overlay生成后的路径存在性检查；
- 测试中明确断言不存在 `D:\桌面\memsharness`。

### P0-3：MCP当前没有PMUT模板

`java_model.TEMPLATES` 当前只有：

```text
heat_slab_2d
cantilever_beam_2d
```

它们是平台验证模板，不是本项目的反相PMUT模型。文档必须明确：

> 现阶段 `sim_submit` 只能提交已注册的演示/验证模板，不能执行 `b_GE_task3_2new_reverse_voltage_drive_v1.mph`、72×7粗扫或45 MHz精扫。

在添加PMUT能力时，必须使用固定、哈希锁定的模型模板，不能开放任意文件路径或任意COMSOL表达式。至少声明：

```text
template_name = pmut_reverse_drive_coarse_v1
source_model_sha256 = cbe9ccc18e51005f6aa147e8d7fdd5df62266c5f9117d9829888336f326582d9
allowed_x_scale = 0.4:0.05:0.8 中二级预检合格集合
allowed_N_w_te1 = 1..8
allowed_freq_MHz = 5,10,15,20,25,30,35
drive_mode = dual_electrode_antiphase_voltage_drive
vamp = 1[V]
term1_active = false
cir_inactive_verified = true
outputs = Ptot,Vave,V_center,V_outer,V_inner,V_ref
```

在该模板完成单组合三频点smoke test以前，禁止让MCP承担LT2。

### P0-4：worker生命周期没有闭环

`sim_submit`只是写队列并返回 `run_id`；返回文本要求另行运行：

```text
python -m memsharness.comsol.queue --max-jobs N
```

如果没有外部worker，任务会永久停在queued。必须在以下两种方案中选择一种并写入文档：

1. **推荐：外部受监督单实例worker。** 启动、PID、锁、健康状态、退出与自动恢复由独立脚本/服务负责；MCP只提交和查询。
2. 新增受限的 `sim_worker_start`，只能启动固定命令、固定仓库、单实例锁、固定最大任务数；不得接受任意shell命令。

无论哪种方案，都必须提供：

```text
worker_running
worker_pid
worker_started_at
worker_lock_owner
last_heartbeat
current_run_id
processed_jobs
```

### P0-5：取消接口默认强杀不安全

当前：

```python
def sim_cancel(run_id: str, force_kill: bool = True)
```

必须改为：

```python
def sim_cancel(run_id: str, force_kill: bool = False)
```

正常取消只写 `cancel.flag`，由worker在安全阶段边界退出。强杀必须同时满足：

- 调用者显式设置 `force_kill=true`；
- `run_id`格式通过验证；
- PID来自该run的受信status；
- 当前PID的启动时间、可执行文件、命令行和run标识与记录一致；
- 不允许终止MCP server、DSH GUI、非本任务COMSOL或其他系统进程；
- 终止后重新检查进程和端口，并记录真实结果。

### P0-6：所有run_id入口必须防路径穿越

`sim_status`、`sim_logs`、`sim_cancel`以及内部 `run_dir(run_id)` 当前未见run_id白名单验证。请在进入文件系统前统一验证，例如：

```text
^run-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$
```

并在路径拼接后验证：

```text
resolved_run_dir is relative to resolved_runs_root
```

非法run_id只返回错误，不读文件、不写 `cancel.flag`、不触碰进程。

## 3. 重要但非阻塞级问题

### P1-1：输入规格还需要上限

`JobSpec.from_dict()` 对以下字段缺少充分约束：

- `backend` 应只允许当前实现的 `local`；
- `timeout_seconds` 建议限制在明确范围，例如60–86400秒；
- `notes/tags/sweep_id/design_id` 应有长度、字符和数量限制；
- 参数虽然已有名称、范围和有限数检查，但应测试 `NaN/Inf`、未知参数、边界值和非扫描参数；
- 单次提交不得隐式展开无限或超大扫描。

### P1-2：`run_trace` 对长任务可能静默截断

`run_trace` 对sample/artifact最多返回200行，而LT2预期504行。如果截断，应返回：

```text
total_count
returned_count
truncated
next_cursor
```

或提供分页。不得把200行响应误解释为任务只产生200行。

### P1-3：文档的技能数量已过时

本机项目技能实际为9个：

```text
ai-solver-verification
autonomous-optimization-loop
comsol-modeling-sop
dataset-contract
field-io-contract
model-io
model-onboarding
report-and-evidence
sweep-analysis
```

把“8个技能”更新为“9个”，并避免在文档中写死会持续变化的数量；最好由验证脚本输出清单和计数。

### P1-4：自测预期输出混合了旧阶段

文档先给出P0的6工具预期，又说P2扩到11个，容易让读者误判。当前验收应只写11工具的完整清单，并把6工具记录移入历史说明。

### P1-5：DSH包目录发现方式过于脆弱

文档中的 `_npx\1e7f6d9597241db0` 是缓存实例，不应作为长期路径。当前现场也未在该位置找到可用 `bin.js`。请改为：

- 优先使用已安装的 `dsh`启动命令；
- 或由安装脚本发现当前包位置并输出；
- 若发现失败，明确跳过 `dump-config` 并标记未验证；
- 不复制旧机器/旧缓存哈希路径。

### P1-6：回滚不能覆盖其他补丁

把整个 `cordis.patch.yml` 恢复为 `[]` 可能删除用户后来加入的其他profile补丁。正确回滚是只删除 `id: mcp-mems-harness` 对应的insert子项，并验证其余条目字节级保留。

预设目录也优先移动到带时间戳的备份目录，而不是直接永久删除。

### P1-7：控制台编码需要统一

selftest输出中的中文发生乱码。建议在启动环境中显式启用UTF-8，或让关键机器可读日志使用UTF-8 JSON/ASCII字段。编码问题不一定阻止工具调用，但会破坏故障证据和自动解析。

## 4. 与当前LT0–LT3任务的关系

### 4.1 当前任务不要等待MCP改造

已下发的 `TO_DEEPSEEK_HARNESS_LT0-LT3执行工单.md` 应继续通过已审核的本地Python/COMSOL批处理流程执行。不要在执行途中切换到尚未验证的MCP队列，以免改变运行口径和证据链。

### 4.2 MCP近期只承担监控

完成P0-1、P0-2、P0-5、P0-6并复验后，可允许：

```text
mcp__mems__ping
mcp__mems__env_report(refresh=false)
mcp__mems__module_capability
mcp__mems__data_stats
mcp__mems__records
mcp__mems__run_trace
mcp__mems__sim_status
mcp__mems__sim_logs
mcp__mems__sim_templates
```

在PMUT模板和worker监督未完成前继续禁用或禁止调用：

```text
mcp__mems__sim_submit
mcp__mems__sim_cancel
```

### 4.3 何时允许MCP提交PMUT

同时满足以下条件后才放行：

```text
selftest_exit_code = 0
headless_ping = pass
headless_tool_list_count = 11
run_id_validation = pass
sim_cancel_default_force_kill = false
pid_ownership_validation = pass
worker_supervision = pass
pmut_template_registered = true
pmut_template_model_sha256_locked = true
pmut_three_frequency_smoke_test = pass
queue_submit_status_logs_cancel_tests = pass
```

## 5. 分层复验方案

### G1：静态安装验证

```powershell
python scripts\verify_mems_install.py
```

要求：profile、preset、9个技能、C盘command/cwd全部通过；overlay也必须纳入该脚本检查。

### G2：MCP进程内自测

```powershell
work\.venv\Scripts\python.exe -m memsharness.mcp_server --selftest
```

要求：退出码0，11工具完整，`ping.ok=true`；数据库不可用时仍应返回结构化 `store_ok=false`，不能崩溃。

### G3：配置组装

使用当前实际DSH启动器执行 `--profile web --dump-config`。要求输出中只有一个 `serverName=mems` 和一个 `id=mcp-mems-harness`，command/cwd存在且无D盘路径。

### G4：headless端到端

使用修复后的overlay实际调用：

```text
ping
sim_templates
sim_status
```

要求三次均成功；stderr可读，不出现乱码路径、重连循环或启动错误。

### G5：队列安全测试

使用玩具模板完成：

1. 合法任务submit立即返回；
2. 没有worker时状态保持queued且说明清晰；
3. 启动单实例worker后任务完成；
4. 第二worker拿不到锁并安全退出；
5. queued任务普通cancel不强杀；
6. 非法run_id/path traversal被拒绝；
7. 终态任务cancel无副作用；
8. 日志分页/截断状态明确。

### G6：PMUT专用smoke test

固定反相模型SHA，只提交基准 `(0.6,4)` 的5/20/35 MHz。核对电极±1 V、Ground 0 V、Circuit停用、Ptot/Vave有限、server清理和全部哈希。通过后才允许真实PMUT队列任务。

## 6. 文档修改要求

修订 `dsh_mcp_registration.md` 时必须：

1. 把标题状态拆成“注册结构”“端到端健康”“PMUT生产能力”三项；
2. 更新为9个技能、11个工具；
3. 删除旧D盘和旧npx缓存路径；
4. 写明 `sim_submit`不会自动启动worker；
5. 写明当前模板仅有两个平台验证模型；
6. 增加工具副作用矩阵：只读、写队列、写数据库、取消/终止进程；
7. 增加数据库被锁/只读时的降级行为；
8. 增加run_id和PID安全策略；
9. 把回滚改为定向删除MEMS条目；
10. 所有“实测通过”后附日期、命令、退出码和产物哈希。

## 7. 下一次回复要求

请先完成P0-1至P0-6及文档修订，不要先扩展更多MCP工具。下一次提交：

```text
docs/dsh_mcp_registration.md
src/memsharness/mcp_server.py
src/memsharness/comsol/queue.py
work/mcp-overlay.patch.yml
tests/test_mcp_*.py
scripts/verify_mems_install.py
docs/TO_CODEX_progress-20260914-mcp-hardening.md
```

报告必须给出G1–G5逐项结果。PMUT模板属于下一阶段；若同时完成，另附G6，不得把玩具模板通过写成PMUT通过。

## 8. 本次证据哈希

| 文件 | SHA256 |
|---|---|
| `dsh_mcp_registration.md` | `c24d818c91dcf8fad5e5e4476a69d2ca75f837e2ab15103706896b332c75e8fe` |
| `mcp_server.py` | `26a3a5a130178ef46703a08cc3b0ae533deca12a5df17c5e8e2841d5dc2681c8` |
| `mcp-overlay.patch.yml` | `af1a4986d5f0f17c78e736a8d488f6310cd5b18125c3119772841a98de0b2691` |
| GUI `cordis.patch.yml` | `dbd84f5950ea19ec4be72b6c5343212072046482888bfc6f18fd4005f6075796` |
| `queue.py` | `5f6982910b76573d245738aaea0b2131a2cfc001b7817ccd399ecb3c7d420ed9` |

---

**最终裁决：MCP的GUI注册结构通过，但端到端自测、headless overlay、数据库只读行为、取消安全、worker闭环和PMUT模板均未达到生产门槛。当前LT0–LT3继续走既有本地批处理；MCP先完成P0-1至P0-6并通过G1–G5，之后只开放监控工具。待PMUT专用模板和G6通过，再允许通过MCP提交真实仿真。**
