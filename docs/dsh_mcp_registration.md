# 把 MEMS Harness 接入 DeepSeek Harness（MCP 集成记录）

目标：让平台工具在 DSH 会话里以 `mcp__mems__<tool>` 的形式可用。

## 1. 接入方式

DSH 通过 `@deepseek-ai/dsh-mcp-client` 插件连接 MCP 服务器。一个实例一个服务器，
配置写在 profile 的用户补丁层：

```
C:\Users\18161\.dsh\profiles\web\cordis.patch.yml
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
        command: 'D:\桌面\memsharness\work\.venv\Scripts\python.exe'
        args: ['-m', 'memsharness.mcp_server']
        cwd: 'D:\桌面\memsharness'
        toolCallTimeoutMs: 60000
        failOnStartupError: false      # MCP 起不来也不许拖垮 GUI
        reconnect:
          enabled: true
```

关键点：

- `failOnStartupError: false`：平台代码出问题时，只是工具不可用，不会导致 GUI 启动失败。
- `toolCallTimeoutMs: 60000`：只读工具够用。**将来加入求解类工具时必须改成「提交返回 run_id + 轮询」**，不要靠调大超时。
- `cwd` 指向仓库根，`command` 用运行区 venv 的解释器；包以 editable 方式安装，故 `-m memsharness.mcp_server` 可解析。

## 3. 验证步骤

1. 先确认服务器能独立启动并注册工具：

```powershell
D:\桌面\memsharness\work\.venv\Scripts\python.exe -m memsharness.mcp_server --selftest
```

预期输出（P0 实测）：

```
已注册工具: data_stats, env_report, module_capability, ping, records, run_trace
ping 返回: {"ok": true, "tool": "mems-harness", "version": "0.0.1", ...}
```

2. 确认补丁**能被组装**（不需要重启服务，这是改动后最快的自检）：

```powershell
D:\node.exe C:\Users\18161\Documents\ChatGPT\deepseek\node_modules\@deepseek-ai\dsh\lib\bin.js --profile web --dump-config
```

P0 实测：组装成功时退出码 0，输出中出现 `# == C:\Users\18161\.dsh\profiles\web\cordis.patch.yml`
与其下的 `- id: mcp-mems-harness` 条目；若补丁写法错误会打印
`patch: entry "xxx" not found` 并以非零退出。

3. 端到端验证（**不影响正在运行的 GUI**）：用 headless 会话叠加同一份补丁，实际调用平台工具。

```powershell
D:\node.exe <dsh安装目录>\node_modules\@deepseek-ai\dsh\lib\bin.js --profile headless `
  --patch D:\桌面\memsharness\work\mcp-overlay.patch.yml `
  "请调用名为 mcp__mems__ping 的工具一次，然后只用一行报告它返回的 version 与 store_tables 字段值。"
```

P0 实测结果（退出码 0）：

```
version=0.0.1，store_tables=12
```

同时 FastMCP 在 stderr 打印 `Server: mems-harness, 4.0.3 / Starting MCP server 'mems-harness' with transport 'stdio'`
——证明 DSH 确实拉起了本平台的 MCP 服务器并完成了工具调用。

4. **需要重启 DSH 服务才能在 GUI 生效。** 实测：仅修改补丁层不会新建条目——
改动后未出现 `memsharness.mcp_server` 子进程（HMR 能热替换既有条目的配置，但不会新增条目）。
重启方式：关闭并重新启动 `start-dsh.cmd`（其内部是自动重启循环）。
重启后刷新 `http://127.0.0.1:3080`，会话中即可调用 `mcp__mems__*`。

> 注意：重启 DSH 会中断当前正在进行的会话回合，请在方便时执行。

5. 关于技能（Skills）：`comsol-modeling-sop` 等技能放在仓库 `.dsh/skills/` 下，
   项目根含 `.git` 故可被技能发现器扫描到。**P0 实测该能力在本会话中已生效**
   （技能目录能动态出现新条目）。因此技能库是一条可用的知识沉淀通道，详见 `docs/skills_enablement.md`。

## 4. 回滚

若接入导致异常，把 `cordis.patch.yml` 恢复为原始内容即可：

```yaml
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
[]
```

## 5. P0 可用工具（只读）

| 工具 | 作用 |
|---|---|
| `mcp__mems__ping` | 健康检查：版本、运行区路径、表数量 |
| `mcp__mems__env_report` | COMSOL/MATLAB/mphserver 环境事实快照（`refresh=true` 重新实测） |
| `mcp__mems__module_capability` | 模块能力表（区分「文档存在」与「求解已验证」） |
| `mcp__mems__data_stats` | 元数据库各表行数 |
| `mcp__mems__records` | 白名单表只读查询（强制行数上限） |
| `mcp__mems__run_trace` | 按 `run_id` 追溯运行 + 样本 + 产物 |

后续阶段加入：`sim_submit` / `sim_status`（P2，异步）、`dataset_build` / `train_surrogate` / `registry_*`（P3–P4）、`experiment_ingest` / `literature_extract` / `feedback_submit`（P5）。
