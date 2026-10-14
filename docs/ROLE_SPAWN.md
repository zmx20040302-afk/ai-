# 角色点名与契约注入（方案 A）

> 9 个子智能体角色的**可点名入口**。本方案**不改动** `~/.dsh` 下的任何预设文件：
> 角色契约的修改**立即生效**（下次 spawn 现读），不需要重启 DSH、不需要改 preset、不需要新会话。

## 0. 为什么不是"把 9 个角色写进 preset"

`dsh-agent-presets` 的组装模型有两条硬事实（本机安装包文档原文）：

1. **子 agent 会加入其父方的组装** —— 它看到的工具与提示词段落和创建它的 agent 相同。
   所以"同一个 preset 内给 9 个角色各配一套工具"在结构上做不到；
2. **新一代组装由组装文件的 mtime+size 触发**，而且"组装文件**旁边**的资产（skill 文件、提示词资产）
   的改动**不会被发现**"——要生效得动组装文件本身或重启进程。

⇒ 把角色契约塞进 preset 反而更脆：改了契约要保证组装文件也动一下，否则子智能体拿到的还是旧契约，
而且这件事**没有任何痕迹**。方案 A 把"契约版本"变成**可核验的哈希**，比"记得重启"可靠。

## 1. 五个动作

```powershell
$py = 'work\.venv\Scripts\python.exe'
$R  = 'C:\Users\zmx\Desktop\memsharness'

# ① 点名（列出 9 个角色：id / 名称 / 类型 / 状态 / 一句话）
& $py -B scripts\spawn_role.py list

# ② 看契约（原文；可只打某一节，例如第 6 节停止条件）
& $py -B scripts\spawn_role.py show a8-verification-freeze
& $py -B scripts\spawn_role.py show a8-verification-freeze --section 6

# ③ 生成可注入载荷（= 子智能体 prompt 全文；--record 追加账本）
& $py -B scripts\spawn_role.py build a8-verification-freeze `
  --task-file work\role-spawns\task_a8_redteam_a5a9.md --record

# ④ 核对载荷（契约漂移即拒绝）
& $py -B scripts\spawn_role.py verify work\role-spawns\<spawn_id>\prompt.md

# ⑤ 看账本 / 集合自检
& $py -B scripts\spawn_role.py ledger --tail 10
& $py -B scripts\spawn_role.py check
```

**spawn 由主智能体完成**：把 `prompt.md` **全文**作为 `subagent` 工具的 `prompt` 注入。
脚本**不代替模型 spawn**（DSH 的 spawn 是模型侧动作）——这是本方案唯一的边界。

## 2. 载荷里有什么

| 段 | 内容 | 为什么 |
|---|---|---|
| 表头 | role_id / 角色目录 / 契约文件 + **契约 sha256** / 任务 sha256 / spawn_id / 生成时刻 / 生成器 sha256 | 事后能回答"那次子智能体用的是哪一版契约" |
| §0 注入须知 | 你是独立子智能体、仓库根、`AGENTS.md` 红线、判定以代码裁决为准、**不要碰 `~/.dsh`** | 子智能体看不到父会话，必须自带边界 |
| §1 角色契约 | 角色目录下的 `AGENT.md` **逐字节原文**，包在 `<!-- BEGIN CONTRACT <sha> --> … <!-- END CONTRACT <sha> -->` 里 | 手抄会漂移；原文可逐字节比对 |
| §2 本次任务 | 任务全文（`--field k=v` 追加"任务参数"小节） | 任务也要可哈希 |
| §3 交付要求 | 由 `agent.json` 派生：入口点 / schema / 测试 / 已知缺口 / 并发边界 / 停止条件 + 固定交付格式 | 让"角色声明"真正约束这一次执行 |

## 3. 三类改动，三种生效方式（这是方案 A 的关键卖点）

| 改什么 | 怎么生效 | 要不要重启 DSH |
|---|---|---|
| `agents/<role>/AGENT.md`、`prompts/spawn.md`、`agent.json` | **立即生效**：下次 `show`/`build` 现读；已发出的载荷会被 `verify` 判 **DRIFT** 并拒绝复用 | 不要 |
| `scripts/spawn_role.py`（生成器本身） | 立即生效；载荷里记了生成器 sha256，可比对 | 不要 |
| `~/.dsh/.agent-presets/mems/**` | **本方案不动它**；若哪天真要动，按 `dsh-agent-presets` 的规矩：动组装文件本身 → 新会话生效 → 需重新安装时用 `install_mems_preset.py --force`（会整份覆盖，别手改） | 视情况 |

## 4. 账本（append-only）

`work/role-spawns/spawn_ledger.jsonl`：每次 `--record` 追加一条

```json
{"kind":"role_spawn","spawn_id":"spawn-<UTC>-<role>-<契约前8位>","role_id":"A8",
 "contract_path":"agents/a8-verification-freeze/AGENT.md","contract_sha256":"…",
 "task_sha256":"…","payload_sha256":"…","created_utc":"…","generator_sha256":"…",
 "fields":{},"task_excerpt":"…"}
```

规则与仓库其它账本一致：**同一 `spawn_id` 内容相同 ⇒ 幂等（noop）；内容不同 ⇒ 拒收**（不许覆盖）。
删除/修改历史记录等于伪造溯源，禁止。

## 5. 常见误用与对应拦截（都有负向用例）

| 误用 | 拦截 | 测试 |
|---|---|---|
| 把任务注入了错误角色 | `build <role>` 只接受 `agents/*/agent.json` 里登记的角色，未知角色退出码 4 | `test_build_rejects_empty_task_and_missing_file` |
| 任务为空（让子智能体自由发挥） | 空任务拒绝出载荷（退出码 4），不落任何文件 | 同上 |
| 拿旧载荷跑新活（契约已改） | `verify` 重算磁盘契约哈希 ⇒ **DRIFT ⇒ 退出码 2**；正文也会逐字节比对 | `test_verify_detects_contract_drift_on_disk`、`test_verify_detects_contract_body_edit_inside_payload` |
| 载荷被手改或与旁车/账本不符 | `verify` 比对 `payload_sha256` ⇒ 退出码 2 | `test_verify_detects_tampered_payload` |
| 想覆盖账本记录 | `append_ledger` 冲突拒收 | `test_ledger_is_append_only` |
| 集合声明指向了不存在的文件 | `check` 逐条核对 `entrypoints/schemas/tests` ⇒ 退出码 2 | `test_check_passes_on_real_repo`（正向）+ `tests/test_agent_collections.py`（结构） |

## 6. 与其它机制的关系

* `agents/README.md` / `docs/ROLE_MAP.md` 由 `scripts/gen_agent_collections.py` 生成 —— **契约正文的唯一来源**；
  本脚本**只读**它们，从不缓存副本（所以不存在"脚本里的旧版本"）。
* `tests/test_agent_collections.py`（22 用例）管**集合结构**；`tests/test_spawn_role_offline.py`（17 用例）
  管**点名/注入/账本**。两者合起来 = "9 个角色可点名且注入无漂移"。
* 人读入口：`agents/README.md`（名册）→ 本文件（怎么点名）→ 具体 `AGENT.md`（角色契约）。
