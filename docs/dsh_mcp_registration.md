# 把 MEMS Harness 接入 DeepSeek Harness（MCP 集成记录）

目标：让平台工具在 DSH 会话里以 `mcp__mems__<tool>` 的形式可用。

> **本机（2026-09-11 起，`C:\Users\zmx\Desktop\memsharness`）现状**：MCP 条目已写入
> `C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml`，「MEMS 模式」预设已装在
> `C:\Users\zmx\.dsh\.agent-presets\mems\`。重装/校验用：
> `python scripts\install_mems_preset.py --install` + `python scripts\verify_mems_install.py`。

## 1. 接入方式

DSH 通过 `@deepseek-ai/dsh-mcp-client` 插件连接 MCP 服务器。一个实例一个服务器，
配置写在 profile 的用户补丁层：

```
C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml
```

## 2. 补丁内容

> **P0 实测纠正（重要）**：补丁层的条目是**定向补丁**，不是直接新增。
> 一个不带 `insert` 的条目会被当作「对既有 id 的覆盖」——找不到该 id 时报
> `patch: entry "xxx" not found`。**新增条目必须包在 `insert:` 里**。

```yaml
# MEMS Harness：把平台工具以 mcp__mems__* 暴露给智能体
# 不带 id 的 insert = 插入到根条目列表
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
        failOnStartupError: false      # MCP 起不来也不许拖垮 GUI
        reconnect:
          enabled: true
```

关键点：

- `failOnStartupError: false`：平台代码出问题时，只是工具不可用，不会导致 GUI 启动失败。
- `toolCallTimeoutMs: 60000`：只读工具够用。**求解类工具走「提交返回 `run_id` + 轮询」**，不要靠调大超时。
- `cwd` 指向仓库根，`command` 用运行区 venv 的解释器；包以 editable 方式安装，故 `-m memsharness.mcp_server` 可解析。
- **`serverName` 不得与其它实例重复**：重复会让后挂载的实例在加载时失败（表现为 preset 选完跳回默认模式）。

## 3. 验证步骤

1. 先确认服务器能独立启动并注册工具：

```powershell
C:\Users\zmx\Desktop\memsharness\work\.venv\Scripts\python.exe -m memsharness.mcp_server --selftest
```

预期（P0 实测为 6 个只读工具；P2 起已扩到 11 个，见第 5 节）：

```
已注册工具: data_stats, env_report, module_capability, ping, records, run_trace
ping 返回: {"ok": true, "tool": "mems-harness", "version": "0.0.1", ...}
```

2. 确认补丁**能被组装**（不需要重启服务，这是改动后最快的自检）：

```powershell
node <DSH包目录>\node_modules\@deepseek-ai\dsh\lib\bin.js --profile web --dump-config
```

<DSH包目录> 可用本机的 npx 缓存路径，例如
`C:\Users\zmx\AppData\Local\npm-cache\_npx\1e7f6d9597241db0`。
组装成功时退出码 0，输出中出现补丁层路径与其下的 `- id: mcp-mems-harness` 条目；
若补丁写法错误会打印 `patch: entry "xxx" not found` 并以非零退出。

3. 端到端验证（**不影响正在运行的 GUI**）：用 headless 会话叠加同一份补丁，实际调用平台工具。

```powershell
node <DSH包目录>\node_modules\@deepseek-ai\dsh\lib\bin.js --profile headless `
  --patch C:\Users\zmx\Desktop\memsharness\work\mcp-overlay.patch.yml `
  "请调用名为 mcp__mems__ping 的工具一次，然后只用一行报告它返回的 version 与 store_tables 字段值。"
```

P0 实测结果（退出码 0）：

```
version=0.0.1，store_tables=12
```

同时 FastMCP 在 stderr 打印 `Starting MCP server 'mems-harness' with transport 'stdio'`，
证明 DSH 确实拉起了本平台的 MCP 服务器并完成了工具调用。

4. **需要重启 DSH 服务才能在 GUI 生效。** 实测：仅修改补丁层不会新增条目——
HMR 能热替换既有条目的配置，但**不会新增条目**（也不会新增 agent preset）。
重启后刷新 `http://127.0.0.1:3080`，**新建会话**即可调用 `mcp__mems__*`。

> 注意：重启 DSH 会中断当前正在进行的会话回合，请在方便时执行。
> 另：**agent preset 在会话创建时锁定**，本会话无法中途切到「MEMS 模式」，必须新建会话。

5. 关于技能（Skills）：SOP 技能放在仓库 `.dsh/skills/` 下，项目根含 `.git` 故可被技能发现器扫描到。
   **实测本机 8 个技能全部生效**（无需装 preset 也有技能）；preset 只决定**人格**，MCP 条目决定**工具**。

## 4. 回滚

把 `cordis.patch.yml` 恢复为原始内容即可（安装脚本会自动备份为 `cordis.patch.yml.bak-<时间戳>`）：

```yaml
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
[]
```

预设回滚：删掉 `C:\Users\zmx\.dsh\.agent-presets\mems\` 整个目录后重启 DSH。

## 5. 当前可用工具（截至 P2）

| 工具 | 作用 |
|---|---|
| `mcp__mems__ping` | 健康检查：版本、运行区路径、表数量 |
| `mcp__mems__env_report` | COMSOL/MATLAB/mphserver 环境事实快照（`refresh=true` 重新实测） |
| `mcp__mems__module_capability` | 模块能力表（区分「文档存在」与「求解已验证」） |
| `mcp__mems__data_stats` | 元数据库各表行数 |
| `mcp__mems__records` | 白名单表只读查询（强制行数上限） |
| `mcp__mems__run_trace` | 按 `run_id` 追溯运行 + 样本 + 产物 |
| `mcp__mems__sim_templates` | 列出已注册的 COMSOL 模板与参数（提交前先用它确定参数名） |
| `mcp__mems__sim_submit` | 提交求解任务到队列并**立即返回 `run_id`**（异步，不长阻塞） |
| `mcp__mems__sim_status` | 查询队列/任务状态 |
| `mcp__mems__sim_logs` | 读取某 run 的日志尾部（定位失败原因） |
| `mcp__mems__sim_cancel` | 取消排队中或运行中的任务 |

后续阶段加入：`dataset_build` / `train_surrogate` / `registry_*`（P3–P4）、`experiment_ingest` / `literature_extract` / `feedback_submit`（P5）。
