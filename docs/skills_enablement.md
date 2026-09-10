# 技能库（Skills）在 DSH Web 下的可用性与启用说明

本文件回答一个问题：**`D:\桌面\memsharness\.dsh\skills\` 下的技能，当前在 DSH 会话里到底能不能被模型读到？**

结论（实测，2026-06 于本机）：**能读到。** 本文同时给出被实测推翻的一个常见误判及其证据，
并给出「若仍需在宿主平面做覆盖」的确切补丁片段、验证方式与回滚方式。

> 是否应用任何补丁由**用户**决定。本文不代替用户开启或关闭任何插件。

---

## 1. 结论摘要

| 问题 | 实测结论 |
|---|---|
| web profile 组装后，宿主平面的 `skill-filesystem` / `tool-skill` 是否 `disabled: true`？ | **是**（`--dump-config` 实测，见第 2 节） |
| 这等于「web profile 下技能库对模型不可用」吗？ | **不等于**。这是**设计如此**：agent 平面（工具与技能）已移到 **agent preset** 之下，由 preset 自己挂载（见第 3 节） |
| 当前会话实际能否看到技能？ | **能**。三个新技能文件写好后，活动会话立刻收到 `<available_skills>` 目录并被替换/更新（见第 4 节），`skill` 工具有效可用 |
| 因此需要在 `cordis.patch.yml` 里把这两个 id 覆盖为 `disabled: false` 吗？ | **不需要**；且这样做会与 preset 的挂载重复，属于未实测的风险动作（见第 6 节） |
| 真正会影响「有没有技能」的因素是什么？ | 会话使用的 **agent preset**：`standard`（名「标准模式」，roster 默认）与 `code`/`cordis` 都挂载技能；`minimal` 不挂载（见第 7 节） |

---

## 2. 实测事实 A：宿主平面的 `--dump-config` 输出

组装命令（在 `D:\桌面\memsharness\` 下执行即可，不需要重启服务）：

```powershell
D:\node.exe C:\Users\18161\Documents\ChatGPT\deepseek\node_modules\@deepseek-ai\dsh\lib\bin.js --profile web --dump-config
```

实测输出（节选，行号为该次输出中的位置）：

```yaml
- id: skill
  name: '@deepseek-ai/dsh-skill'
# == @deepseek-ai/dsh-base, patched by @deepseek-ai/dsh-web-app
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'
  disabled: true
# == @deepseek-ai/dsh-base
- id: skill-badge
  name: '@deepseek-ai/dsh-skill-badge'
  disabled: true
# == @deepseek-ai/dsh-base, patched by @deepseek-ai/dsh-web-app
- id: tool-skill
  name: '@deepseek-ai/dsh-tool-skill'
  disabled: true
```

以及客户端侧（**启用**）：

```yaml
- id: ui-skill
  name: '@deepseek-ai/dsh-client-ui-skill'
```

事实要点：

- `skill`（`@deepseek-ai/dsh-skill`，技能**注册表**）与 `ui-skill`（`@deepseek-ai/dsh-client-ui-skill`）**启用**。
- `skill-filesystem`（`@deepseek-ai/dsh-skill-filesystem`）与 `tool-skill`（`@deepseek-ai/dsh-tool-skill`）
  被 `@deepseek-ai/dsh-web-app` 置为 `disabled: true`；`skill-badge` 也是 `disabled: true`。
- 这些 `disabled: true` 位于 profile 组装树的**根（宿主平面）**，即 `--dump-config` 打印的那一层。

**这一步的事实没有问题；问题出在从它推出的结论。** 见下一节。

## 3. 实测事实 B（决定性）：`dsh-web-app` 为何这么做

`@deepseek-ai/dsh-web-app` 的补丁文件里有原文注释（文件：
`C:\Users\18161\Documents\ChatGPT\deepseek\node_modules\@deepseek-ai\dsh-web-app\cordis.patch.yml`，
约第 345–356 行）：

> The `skill` REGISTRY stays in the host plane. It is host+per-scope layered (the tools-registry shape):
> deployment-level providers — repository plugins, a host skill-filesystem row — register into its global
> layer, while a preset's `skill-filesystem` registers into that preset's layer, and each agent reads the
> merged catalog its scope chain selects. Only the per-agent rows move behind presets: the base host
> `skill-filesystem` row is disabled here (**presets own local discovery**), and `tool-skill` is what a
> preset mounts to give its agent the catalog and loader at all.

也就是说：

- 技能的**注册表**（`skill`）留在宿主平面，且按 scope 分层。
- **本地发现**（`skill-filesystem`）与**面向模型的目录 + 加载工具**（`tool-skill`）是**每 agent 的行**，
  已移到 **agent preset** 平面；宿主平面的那两行被显式关掉，正是为了「preset 自己拥有本地发现」。
- 因此根层 `disabled: true` **不代表技能不可用**，只代表「根层不再提供它，由 preset 提供」。

实测 preset 文件（随应用安装，只读、`system` 信任）：

`...\node_modules\@deepseek-ai\dsh\config\agent-presets\standard\agent.cordis.yml`（约第 76–87 行）：

```yaml
# ── skills ──────────────────────────────────────────────────────────────────
# The skill REGISTRY lives in the host composition and is layered per scope:
# these rows register into THIS preset's layer of it, so they need no realm.
# `skill-filesystem` contributes local-root discovery for agents on this preset, and
# `tool-skill` gives them the catalog and loader; the merged catalog also
# carries whatever the deployment registered globally (repository plugins).
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'

- id: tool-skill
  name: '@deepseek-ai/dsh-tool-skill'
```

各 preset 的实测情况：

| preset | 目录 | 是否挂载 `skill-filesystem` + `tool-skill` |
|---|---|---|
| `standard`（名「标准模式」） | `config\agent-presets\standard\agent.cordis.yml` | **是**（另见 `preset.yml`：description 明写支持 Skills） |
| `code` | `config\agent-presets\code\agent.cordis.yml` | **是** |
| `cordis` | `config\agent-presets\cordis\agent.cordis.yml` | **是**（且用 `customSkillDirs` 挂载 preset 自带的 `skills/` 目录） |
| `minimal` | `config\agent-presets\minimal\agent.cordis.yml` | **否**（该文件中无 skill 相关行） |

roster 默认值由 web-app 补丁设定：

```yaml
- insert:
    - id: agent-presets
      name: '@deepseek-ai/dsh-agent-presets'
      config:
        default: standard
```

`config/agent-presets/` 随部署安装、只读；`$DSH_HOME/.agent-presets` 是个人可写根
（本机实测：`C:\Users\18161\.dsh\.agent-presets` **不存在**，即目前没有自定义 preset）。

## 4. 实测事实 C：现场验证（决定性）

在 `D:\桌面\memsharness\.dsh\skills\` 下依次写入三个技能后，**活动中的 DSH 会话立即**收到技能目录更新：

- 写入 `.dsh\skills\comsol-modeling-sop\SKILL.md` 后，会话收到含 `comsol-modeling-sop` 的
  `<available_skills>` 目录，并且 `skill` 工具在会话中可用。
- 写入 `.dsh\skills\dataset-contract\SKILL.md` 后，收到**完整替换目录**（含前两个技能）。
- 写入 `.dsh\skills\report-and-evidence\SKILL.md` 后，收到含三个技能的完整替换目录。

**结论：当前 web 会话下技能库对模型是可用的**，「当前 web profile 下技能库对模型不可用」这一判断不成立。

运行中的服务确实用的是 web profile，证据两条：

1. 进程命令行（实测）：`D:\node.exe ...\@deepseek-ai\dsh\lib\bin.js web`，
   由 `C:\Users\18161\Documents\ChatGPT\deepseek\start-dsh.cmd` 托管启动（未显式传 `--profile`；
   `bin.js web --help` 的用法行即 `dsh --profile web [options]`）。
2. **web profile 的补丁层在会话中确实生效**：`C:\Users\18161\.dsh\profiles\web\cordis.patch.yml` 里
   `insert` 的 `mcp-mems-harness` 条目，在会话中以 `mcp__mems__ping` 等工具形式可用
   （`insert` 位于 web profile 的用户补丁层，只有该层被组装时才可能出现）。

因此第 3、4 节的 preset 平面结论，适用于当前 GUI 上的真实会话，而不只是配置文本。

## 5. 技能发现规则与文件格式（实测自插件文档）

来源：`...\node_modules\@deepseek-ai\dsh-skill-filesystem\README.md`。

发现根（按 rank 顺序）：

| Rank | 来源 | 路径 |
|---|---|---|
| 100 | `project-dsh` | `<projectRoot>/.dsh/skills` |
| 200 | `project-agents` | `<projectRoot>/.agents/skills` |
| 300 | `custom` | `Config.customSkillDirs`（preset 可用） |
| 400 | `user-dsh` | `<dshHome>/skills` |
| 500 | `user-agents` | `<agentsHome>/skills` |

- **projectRoot = 最近的含 `.git` 的祖先目录**；没有 `.git` 时回退到当前 cwd。
  `D:\桌面\memsharness\.git` 实测存在，因此 `.dsh\skills` 是有效技能根。
- **发现只做一层**：只认 `<root>/<name>/SKILL.md` 与 `<root>/<name>.md`；
  嵌套的 `**/SKILL.md` 故意不识别。
- frontmatter 为开放 YAML：必填 `name`、`description`；可选 `whenToUse`、`metadata`、
  `disable-model-invocation`、`user-invocable`。**`name` 必须是 kebab-case**（与目录名一致）。
- 写了 `disable-model-invocation: true` 会把该技能从面向模型的目录与加载器中排除。
- 面向模型的目录只渲染 `name` + `description`，描述按 `catalogDescriptionMaxLength`（默认 500）截断；
  `whenToUse` 不进目录（但它仍是本仓库约定要填的字段）。
- 目录会随文件变化热刷新（插件带 `watch`，默认 `true`），因此**新增/修改技能文件不需要重启 DSH**。
  本次三个技能文件全部在服务运行中被即时发现。

本仓库三个技能的落点：

```
D:\桌面\memsharness\.dsh\skills\comsol-modeling-sop\SKILL.md
D:\桌面\memsharness\.dsh\skills\dataset-contract\SKILL.md
D:\桌面\memsharness\.dsh\skills\report-and-evidence\SKILL.md
```

## 6. 若仍需在宿主平面覆盖这两个 id（补丁片段）

> ⚠️ **本节内容是「照办可行但不必做」，并带有未实测的风险。** 第 2–4 节已证明技能在 preset 平面已经可用；
> 在宿主平面再开一份 `skill-filesystem` / `tool-skill` 会造成**同一批技能被两个 provider 同时提供**，
> 合并目录里可能出现重名条目。**该后果本机未实测。** 除非有明确理由（例如把 preset 固定成 `minimal`
> 但仍要技能），否则不建议应用。

### 6.1 补丁片段

`C:\Users\18161\.dsh\profiles\web\cordis.patch.yml` 是用户补丁层（在全部 bundle 层之后应用），
顶层是 **YAML 数组**。已有条目的字段用**不带 `insert` 的 `{id, ...覆盖字段}`** 写法；
新增条目必须写成 `{insert: [ ...条目... ]}`（不带 id 的 `insert` 插到根列表；带 id 的 `insert` 追加到该 group 的 config）。

对**既有 id** `skill-filesystem` 与 `tool-skill` 做覆盖，追加如下两段（保持为顶层数组元素，**不要**放进 `insert`）：

```yaml
# ---- 在宿主平面启用技能发现与技能工具（覆盖既有 id 的 disabled 字段）----
- id: skill-filesystem
  disabled: false

- id: tool-skill
  disabled: false
```

注意：

- 这两个条目**必须**是顶层数组元素、且**必须带 `id`**。写成不带 `insert` 又没有 id 的条目会被当作
  「对既有 id 的覆盖」而在找不到 id 时报 patch 错误。
- 只覆盖 `disabled` 字段即可，不要重复写 `name`（除非确实要换包）。
- 已有的 `- insert: [...]`（`mcp-mems-harness`）不要动。

### 6.2 生效方式

- **需要重启 DSH 服务**（本机由 `start-dsh.cmd` 托管，重启该脚本拉起的进程）。
  补丁层改动以重启为可靠路径；本机记录显示 MCP 插件行的新增曾通过 profile 内 HMR 热加载而无需重启
  （见 `docs/dsh_mcp_registration.md` 第 3 节），但**插件行的启用/禁用是否同样免重启，本机未单独实测**。
- 与此相对，**只增改 `.dsh/skills/` 下的技能文件不需要重启**（第 5 节实测）。

### 6.3 验证

不重启也能验证补丁是否被组装进去：

```powershell
D:\node.exe C:\Users\18161\Documents\ChatGPT\deepseek\node_modules\@deepseek-ai\dsh\lib\bin.js --profile web --dump-config
```

在输出中定位 `skill-filesystem` 与 `tool-skill` 两个条目：

- 覆盖生效：这两处**不再出现** `disabled: true`。
- 未生效：仍能看到 `disabled: true`（说明补丁没被解析，或条目写法/位置不对，例如误放进了 `insert`）。

**注意范围**：`--dump-config` 打印的是 profile 的组装树（宿主平面），**不包含** agent preset 的
`agent.cordis.yml`（那是独立文件，按 preset 名解析）。因此：

- 用 `--dump-config` 只能验证**宿主平面**这两行是否被启用，不能据此判断技能对模型是否可用。
- 要判断「模型到底能不能看到技能」，用第 7 节的方法。

### 6.4 回滚

把新增的两段删掉即可。为便于回滚，本机补丁层在加这两段之前的内容是：

```yaml
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).

# ---- MEMS Harness：把平台工具以 mcp__mems__* 暴露给智能体 ----
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
        failOnStartupError: false
        reconnect:
          enabled: true
```

回滚步骤：删除 `- id: skill-filesystem` / `- id: tool-skill` 两段 → 重启 DSH 服务 →
再跑一次 `--dump-config` 确认这两处重新出现 `disabled: true`。
（若回滚出问题，把 `cordis.patch.yml` 整体恢复为上面的原始内容即可。）

## 7. 真正该检查的地方：会话用的 agent preset

技能「有没有」由 preset 决定，不由第 2 节那两行决定。排查顺序：

1. **看会话用的 preset**：GUI 的 General 设置里有 agent-preset 选择项（`ui-agent-preset`）。
   roster 默认是 `standard`（「标准模式」，description 明写支持 Skills）。
2. **换 preset 会影响技能可见性**：切到 `minimal` 后，该会话不再挂载 `skill-filesystem` / `tool-skill`，
   技能目录与 `skill` 工具都会消失。`standard` / `code` / `cordis` 不受影响。
3. **确认技能文件落点与格式**：必须是 `<projectRoot>/.dsh/skills/<kebab-name>/SKILL.md`（一层，不嵌套），
   `name` 为 kebab-case 且与目录名一致，frontmatter 有 `description`，且**没有** `disable-model-invocation: true`。
4. **确认 projectRoot**：最近的含 `.git` 的祖先。`D:\桌面\memsharness\.git` 实测存在。
5. **（可选）自定义 preset**：`$DSH_HOME/.agent-presets` 是个人可写根。本机实测该目录**不存在**。
   若要自定义，应复制 `standard` 再改，而不是原地改只读的 `config/agent-presets/`。

## 8. 决策归属

- **是否应用第 6 节的补丁，由用户决定。** 本文件不替用户开启或关闭任何插件，也没有替用户改写
  `C:\Users\18161\.dsh\` 下的任何文件。
- 若目标只是「让这三个技能在会话里可用」：**当前无需任何补丁**，第 4 节已实测可用。
- 若要调整技能的可见范围（例如某个 preset 不挂技能），那是 preset 层的改动，不是 profile 补丁层的改动。

## 9. 本文件的证据来源

| 主张 | 来源 |
|---|---|
| 宿主平面 `skill-filesystem`/`tool-skill` 为 `disabled: true`，`skill`/`ui-skill` 启用 | `--profile web --dump-config` 实跑输出 |
| 「preset 拥有本地发现」是该 `disabled` 的原因 | `dsh-web-app\cordis.patch.yml` 原文注释 |
| `standard`/`code`/`cordis` preset 挂载两个 skill 行、`minimal` 不挂载 | 各 `config\agent-presets\*\agent.cordis.yml` 实读 |
| roster 默认 preset 为 `standard` | `dsh-web-app\cordis.patch.yml` 中 `agent-presets` 的 `config.default` |
| 技能在活动中被即时发现、`skill` 工具可用 | 本会话现场观察：三个技能文件写入后连续三次收到 `<available_skills>` 目录更新 |
| 技能根、一层发现、frontmatter 字段、`watch` 默认开启 | `dsh-skill-filesystem\README.md` |
| 运行中服务与 profile | 进程命令行 `...\dsh\lib\bin.js web`、`start-dsh.cmd` |
| MCP 插件行曾免重启热加载 | `docs\dsh_mcp_registration.md` 第 3 节 |
