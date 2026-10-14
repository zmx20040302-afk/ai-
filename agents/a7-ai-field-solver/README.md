# 子智能体集合：A7 AI 场求解器

类型：**确定性执行体（代码 + MCP）** ｜ 状态：契约版（骨架已有；S1 fail、S3 not_measurable）

## 这个集合里有什么

| 文件 | 用途 |
|---|---|
| `AGENT.md` | 角色契约（spawn 时**原文注入**给子智能体） |
| `agent.json` | 机器可读元数据（类型/状态/输入输出/入口点/契约/测试/并发/禁止） |
| `prompts/spawn.md` | 自包含 spawn 提示词（不依赖主对话上下文） |
| `README.md` | 本文件：怎么用、怎么验 |

## 怎么用

1. **点名 + 契约原文注入**（推荐，方案 A；不改 DSH preset、改契约立即生效）：

   ```powershell
   $py = 'work\.venv\Scripts\python.exe'
   & $py -B scripts\spawn_role.py list                       # 九个角色的 id/状态
   & $py -B scripts\spawn_role.py show A7                   # 看本角色契约原文
   & $py -B scripts\spawn_role.py build A7 --task-file <任务.md> --record
   & $py -B scripts\spawn_role.py verify work\role-spawns\<spawn_id>\prompt.md
   ```

   然后把 `prompt.md` **全文**作为 `subagent` 的 prompt 注入；`--record` 会在
   `work/role-spawns/spawn_ledger.jsonl` 留一条 append-only 记录（哪版契约 + 什么任务 + 哈希）。
   说明与边界见 `docs/ROLE_SPAWN.md`。
2. 也可以直接按 `prompts/spawn.md` 起子智能体，但**必须**逐字注入 `AGENT.md`（手抄会漂移，
   且漂移无痕迹）；
3. 子智能体的产物按 `agent.json.outputs` 落盘；
4. 判定类结论引用 `agent.json.entrypoints` 里**代码**产出的裁决文件，而不是自述。

## 怎么验（本集合是否"自描述且诚实"）

```powershell
work\.venv\Scripts\python.exe -B scripts\gen_agent_collections.py --check   # 契约与磁盘一致
work\.venv\Scripts\python.exe -B -m pytest tests\test_agent_collections.py -q # 集合结构与引用可解析
work\.venv\Scripts\python.exe -B scripts\spawn_role.py check                 # 声明路径 + 名册覆盖
```

`tests/test_agent_collections.py` 会检查：九个集合齐备、`agent.json` 可解析、
**声明的入口点/契约/测试文件在磁盘上真实存在**（声明的工具不许是空头支票）；
`tests/test_spawn_role_offline.py` 会检查：载荷里契约**逐字节一致**、契约漂移会被 `verify` 拦住、
账本 append-only。

## 现有入口点

- src/memsharness/pod.py
- src/memsharness/consistency.py
- scripts/check_s3.py

## 缺口

- 场数据接口（`p_axis_100um` 频响、`V_outer/V_inner`）
- FNO/DeepONet 未实现
- S3 可测化（L1 网格收敛 / COMSOL 残差 / 功率平衡）
