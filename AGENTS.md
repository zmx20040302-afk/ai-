# MEMS Harness — 项目级智能体指令

本文件是整个仓库的最高优先工作约定。任何在此仓库内的工作都必须遵守；与用户当场指令冲突时，以用户指令为准。

## 1. 项目定位

把「人给一句需求」变成「平台自动跑 COMSOL → 生成/扩充数据 → 训练 AI 求解器与代理模型 → 用实验、文献、人反馈持续增强 → **最终在不调用 COMSOL 的前提下完成求解** → 输出可追溯、带误差界的结论」的闭环平台。

**终局形态（v0.2）**：COMSOL 的定位是**教师 + 验证器 + 兜底裁判**（生成高保真真值、做独立留出集验证、AI 超范围时回退），**日常求解由 AI 求解器完成**。

完整设计见 `WORKING_PLAN.md`。当前阶段与验收标准以该文档第 7 节（P0–P7）为准；免求解器的指标与门禁见第 6.1.1 / 6.4 节。

## 2. 不可协商的红线

1. **没有证据就不出数字。** 报告里的每个数值必须能追溯到 `run_id`（仿真）、`evidence_id`（文献，含页码与原文摘录）、`experiment_id`（实验）或 `feedback_id`（人反馈）。工具没返回的数值，禁止凭记忆或推测填写。
2. **物理正确性优先于 AI 指标。** 代理模型的误差只在解析解校验（L0）与网格收敛校验（L1）通过后才被采信；未过 L4 留出集阈值的模型只允许谈趋势，禁止输出用于工程判断的绝对值。
3. **不猜测模型内部。** `.mph` 是专有格式：读不到参数/物理场/研究设置就如实报告「需要导出摘要或 API 读取」，不得根据文件名或惯例编造设置。
4. **来源永不混同。** 仿真值、解析值、文献值、实验值、人反馈值在存储中带独立 `source_type` 与权重，任何统计、训练、报告都必须显式声明混用了哪些来源。
5. **人保留放行权。** 模型状态从 `draft` 升到 `approved_for_use` 必须经人工门禁；智能体不得自行晋升模型状态，也不得把「待验证」描述为「已验证」。
6. **历史 append-only。** 数据与结论的修正通过新增记录实现，不覆盖既有记录。
7. **AI 求解器可以替代求解，但必须有界。** 免 COMSOL 出解必须同时具备三样东西：**场级误差界**、**S 级验证状态**（见 `WORKING_PLAN.md` 6.1.1 / 6.4）、**适用范围命中判定**。超出已声明范围 → **拒答并回退 COMSOL**，禁止无界外推；物理一致性检查（守恒/边界条件/对称性/极限一致性）不通过的解一律作废——**哪怕它与数据吻合**。AI 解不得伪装成 COMSOL 解，也不得声称「已验证等价于 COMSOL」。
8. **AI 求解值是独立来源。** `source_type = 'ai_solver'`，与 `simulation` 严格区分，必须携带误差界与验证等级；不得与 COMSOL 结果混为同一来源做统计或训练。

## 3. 环境事实（P0 实测，勿凭印象改写）

> 本节记录**当前工作机**（2026-09-11 起，`C:\Users\zmx\Desktop\memsharness`）的实测值。
> 旧机（`D:\桌面\memsharness` + `C:\Users\18161\memsharness_work\repo` 交汇点，MATLAB R2025b）
> 的历史事实见 `WORKING_PLAN.md` 第 2/13 节，**勿再据此操作本机**。

| 项 | 值 |
|---|---|
| 仓库根 | `C:\Users\zmx\Desktop\memsharness`（**纯 ASCII 路径 → 不需要 ASCII 交汇点**；旧机的中文路径问题在本机不存在） |
| 运行区 | 仓库内 `work\`（数据/模型/产物；已 gitignore） |
| Python 环境 | `work\.venv\Scripts\python.exe`（Python 3.12.14；本机**未装 uv**，用 `python -m venv` 建。若将来把仓库移到中文路径，再回到 `uv venv`） |
| **venv 内沙箱补丁** | `work\.venv\Lib\site-packages\sitecustomize.py` 把 `os.mkdir/makedirs` 的 mode 强制为 `0o777`。原因：受限文件策略下沙箱拒绝写入「以 0o700 创建」的目录，而 `tempfile.mkdtemp`/pip/venv 内部正是如此 → 不补则 pip 全流程 `PermissionError: [Errno 13]`（实测）。全权限策略下非必需，保留无害 |
| COMSOL | `D:\COMSOL64\Multiphysics`（**6.4.0.293**）；本机**另装有 6.2**（`D:\COMSOL62`），默认用 6.4 |
| COMSOL 批量 / 编译 | `D:\COMSOL64\Multiphysics\bin\win64\comsolbatch.exe`、`comsolcompile.exe` |
| **COMSOL × 文件策略（硬约束）** | 实测：`workspace-write` 下 `comsolcompile`/`comsolbatch` **统一 rc=15 且 stdout/stderr 全空**（连最小 `Hello.java` 都失败）；`-userdir`、`COMSOL_USERHOME`、覆盖 `USERPROFILE/HOME/APPDATA` 三种重定向**均无效**；`danger-full-access` 下同一命令 **rc=0** 并产出 `.class`。→ **任何真实 COMSOL 步骤都必须在放宽的文件策略下执行**，否则会得到「静默失败」 |
| mphserver | `comsolmphserver.exe`，`127.0.0.1:2036`；**本机默认不常驻**，用前显式启动并探测端口。⚠️ 平台能力表 `module_capability` 的 `mphserver_listening` **可能是缓存值**（实测曾报 `true` 而现场探端口 **2036 CLOSED**）⇒ 端口存活一律**现场探**，不得引用快照 |
| MATLAB | `D:\matlab\bin\matlab.exe`（**R2023b**，ProductVersion 23.2.0.2344743；本机另有 `D:\Matlab2023b`）；LiveLink 路径 `D:\COMSOL64\Multiphysics\mli` |
| COMSOL API schema | `D:\COMSOL64\Multiphysics\data\completion\physics.xml`（实测 1750 特征 / 7239 变体 / 16886 枚举属性） |
| DSH Web GUI | `http://127.0.0.1:3080`；profile 补丁层 `C:\Users\zmx\.dsh\profiles\web\cordis.patch.yml` |
| MEMS 模式（DSH 预设） | `C:\Users\zmx\.dsh\.agent-presets\mems\`——**用户级状态，不在仓库里**，迁移不会自动带过来；安装/校验见 `scripts\install_mems_preset.py`、`scripts\verify_mems_install.py`。**预设与 MCP 补丁都在 DSH 启动时装载，装完必须重启 DSH 并新建会话** |
| **目标器件** | `C:\Users\zmx\Desktop\b_GE_task3_2-new.mph`（98.9 MB，SHA256 `3efa34cc…`）= 用户 2026-09-11 确认的**当前目标器件**；`b_GE_task3_2-new  n7.mph`（528 MB）与 `b_GE_task3_2-newyizu.mph`（4.25 GB）为**参数化扫描用**模型。三者均在**仓库外**，按只读引用处理（`probe_model` 会自行复制副本并记录源 SHA256） |
| Shell | 本机是 **Windows PowerShell 5.1**（`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`，**没有 `pwsh`**：脚本里调 `pwsh` 会 `CommandNotFound`）；Process 执行策略 = **Bypass**（可直接 `& script.ps1`）。⚠️ **`.ps1` 必须存为 UTF-8 with BOM**：5.1 对无 BOM 脚本按 ANSI/GBK 解码，中文日志会变成乱码并触发解析错误（2026-09-13 实测：`work\tools\run_precheck_when_free.ps1` 两次失败后才定位）。**同理：统计/校验 UTF-8 文本（行数、反引号配平、表格列数）一律用 Python 或 read 工具，不要用 `Get-Content`**——它按 GBK 回退解码会给出错误行数（实测同一文件 `Get-Content` 报 313 行 / 真实 425 行）；**也不要把反引号写进 PowerShell 双引号 here-string**（反引号是转义符，会静默毁掉被包裹的代码） |
| **内存 / 提交限制（2026-09-14 实测）** | 物理内存 **32,189 MB**；页面文件 `C:\pagefile.sys` **系统自动管理、仅分配 4,873 MB**（当前用 833 / 峰值 915 MB）⇒ **commit limit 仅 37,055.6 MB**（38,863,409,152 B），只比 RAM 高 4.9 GB。空闲 Committed Bytes ≈ **25.3 GB**（各进程 PrivateBytes 合计 17.6 GB，余为内核/分页池），空闲可用物理内存 ≈ 16.9 GB。→ **本机空闲时可给 COMSOL 的 commit 余量约 11.1 GB，而 11 GB 级模型的 COMSOL 峰值提交量正好也是 11.2 GB**，故运行期 commit 余量会贴地到 0.6–1.3 GB 并**仍能成功**——这是页面文件过小导致的算术必然，不是 COMSOL 异常，也不是本机能力上限。⚠️ 因此「commit 余量低」不能当作故障前兆；要真正留出余量须调大页面文件（系统级改动，需用户拍板）。**注意 `PeakWorkingSet` 单调不减，不能用作实时内存信号**，实时量看 `WorkingSet` |
| **进程存活判定与终止后验证（2026-09-14 实测）** | ① **不能用 `OpenProcess` 判进程是否存活**：目标被终止后，只要其父进程（如 `subprocess.Popen`）仍持有句柄，`OpenProcess` 依然成功 ⇒「能否打开」恒为真，会把「已成功终止」误判为失败（实测导致 4 项自测假失败）。正确做法：`GetExitCodeProcess(h) == STILL_ACTIVE(259)` 才算存活。② **终止后不能只查一次**：`Stop-Process` 返回 rc=0 之后 PID 与端口不会立刻同时消失，必须**带超时轮询**（实测 PID 约 15 s / 端口约 10 s），并把 `waited_s`/`timed_out` 留痕。③ 测试替身/依赖注入：若基类定义了同名方法、而实现读取的是**实例属性**，子类方法会被实例属性遮蔽导致 fake 不生效（实测误判为「拒绝终止」通过）⇒ 注入点必须赋实例属性。④ **含墙钟时间戳的自测产物哈希不可复现**：同一自测连跑两次产物逐字节不同，报告中引用其 sha256 会制造假异常 ⇒ 需固定时间戳/种子模式，或显式标注「不可复现」 |
| **DSH 重启会杀掉它的后台作业（2026-09-24 实测）** | DSH 把自己的后台作业进程放进一个 Windows **Job 对象**；**DSH 一重启，Job 被拆，里面所有子进程被一起终止**。实测：14:34:04 DSH（`node …dsh/lib/bin.js web --port 3080`）换进程后，`pwsh-1`（8899 看板）与 `pwsh-4`（8877 控制台）**同时**死亡——前者 `killed` 且子进程报 `1073807364 = 0x40010004 = DBG_TERMINATE_PROCESS`，后者 `exit code 1`（Windows 强杀码，**无** signal 标记）；**机器并未重启**（已连续运行 42 h）。⚠️ 同一会话的作业注册表也随之清空（旧 job id 查询返回 `unknown job`）。⇒ **需要长期在跑的服务必须脱离 Job 启动**：用 **WMI `Win32_Process.Create`**（父链落在 `WmiPrvSE.exe`/`services.exe`，**不是** DSH），**不要用 `Start-Process`**（仍在 Job 内，会被一起杀）。现成实现：`scripts\serve_detached.ps1 -Action start\|stop\|status\|restart`，说明见 `docs\WEB_SERVICES.md`；脱离后**在 DSH 的 jobs 列表里看不到它们**，别误以为"没在跑"。⚠️ **默认策略 = 按需启动、不常驻**（用户 2026-09-25 指示）：**不做登录自启/定时自愈**，要用时跑可双击的 `work\tools\start_web_services.cmd`；**机器重启后需手动跑一次**。`scripts\install_web_services_task.ps1` 是**可选**的常驻安装器，其默认动作是 `show`（不是 `install`）。注意区分两件事：**"DSH 重启不影响它们"（已脱离 Job）≠ "机器重启不影响它们"（会没）** |
| **`.ps1` 的第二个必踩坑：`param()` 必须是第一条语句（2026-09-24 实测）** | 除"必须 UTF-8 with BOM"（见 Shell 行）外：本仓库 `scripts\serve_detached.ps1` 初版在开头写了 **Python 风格的 `"""…"""` 文档串**，PowerShell 把它当**表达式**⇒ 直接报 `param : The term 'param' is not recognized`。**PowerShell 的块注释是 `<# … #>`**。两个坑都已固化为用例 `tests\test_web_services_detached.py`（并锁住 `.cmd` 必须**纯 ASCII**——cmd.exe 按 OEM 代码页读、端口与脚本名在 `.ps1`/`.cmd` 间一致、代码体里不得出现 `Start-Process`） |
| 网络 | 官方 `files.pythonhosted.org` 读超时；`pypi.tuna.tsinghua.edu.cn` 可用但索引页偶发截断（需重试收敛）；**`mirrors.aliyun.com` 会截断大 wheel**（实测 duckdb 只下到 3,515,967/13,168,544 B 却无异常） |
| 只读输入源 | 旧机的 `D:\桌面\codex\comsol1`、`D:\桌面\换能器学习`、`D:\桌面\mems论文` 在本机**不存在**；需要时向用户索取 |

## 4. 执行约定

- **长任务必须异步。** COMSOL 求解动辄数分钟到数小时：走 `sim_submit` 拿 `run_id` + 轮询 `sim_status`，或用 DSH `jobs` 后台作业。**禁止**把长求解放进同步工具调用（MCP 默认 60 s 超时会中断）。
- **求解环节禁止并行扇出。** COMSOL 受 license 与内存约束，必须单实例串行队列。DSH `workflow` 只用于非求解工作的并行（解析计算、文献抽取、报告撰写、代码审查）。
- **运行前检查锁。** 若目标 `.mph` 旁存在 `.lock`（GUI 打开中），先复制到 `work\` 下再操作，不要直接改动生产模型；生产模型一律只读引用。
- **一次运行一个目录。** 每次求解的输入、命令、日志、输出、软件版本、模型哈希全部落在 `work\runs\<run_id>\`，使其可独立复现。
- **不改别人的数据。** 本机的只读输入源是**仓库外**的模型与资料（如 `C:\Users\zmx\Desktop\b_GE_task3_2-*.mph`、用户提供的论文/实验数据）；需要改动时先复制到 `work\` 下再操作。
- **读 `.m` 参数一律取"最后一次 `param.set`"。** COMSOL 导出的 `.m` 会在文件**末尾**再覆盖一次参数：实测 `b_GE_task3_2new.m` 与 `b_GE_task3_2newyizu.m` 均在 **L2389** 把 `N_w_te2` 由 L78/L157 的 `5` 覆盖为 `9`（紧接 `geom.run('fin')`），故运行态真值是 **9**。
  文件头的值**已失效**；用 `Select-String | Select-Object -First N` 截断输出会漏掉末尾覆盖并得出错误结论（2026-09-13 实测踩坑）。取参数按最后一次出现为准，并把行号作为证据留档。
- **判定"某 API 不存在"必须查到接口/基类层，并与官方文档交叉验证。** 实测教训（2026-09-13）：我只查了 `com.comsol.model_1.0.0.jar` 的 `*Method` **实现层**类（`GeomMeasureMethod`/`GeomMeasureFinalMethod`），据此断言「COMSOL 几何测量接口没有面积方法」，并把这条错的"更正"发给了外部审阅方。**该结论错误**：接口层 `com/comsol/model/dbimodel/GeomMeasureBase.class` 含 `getArea`（javadoc 原文 "Gets area of the selected faces or 2D domains"）与 `getBoundaryArea`，官方 6.4 文档 `com.comsol.model.GeomMeasureBase` 一致。
  **一个实现类里没有 ≠ 整个 API 没有。** 离线取证要同时查接口/基类层（`dbimodel`/`definition`）与官方 API 文档，并用 `work\tools\probe_comsol_api.py scan <jar> <描述符>` 定位"谁声明了该方法"。
- **COMSOL 步骤要求放宽的文件策略。** 受限策略下 COMSOL 启动器会**静默失败**（rc=15、无输出、无产物），不要把它当成模型或代码问题（详见第 3 节）。跑 COMSOL 前先确认会话的文件策略已放宽。
- **生产模型不进仓库。** 目标器件与扫描用模型都放在仓库外，`work\` 下只保留只读副本、探针产物与求解 run（含哈希与命令留档）。

## 5. 工作产物落点

| 内容 | 位置 |
|---|---|
| 设计与计划文档 | 仓库根、`docs\` |
| 契约与 schema | `schemas\` |
| 可执行脚本（一次性/运维） | `scripts\` |
| 平台代码 | `src\memsharness\` |
| 测试 | `tests\` |
| 技能（SOP） | `.dsh\skills\<name>\SKILL.md` |
| 运行数据/模型/报告 | `work\`（不进版本库） |

## 6. 交互与写作约定

- 对用户使用中文；代码注释以中文为主，标识符与键名用英文。
- 单位：内部一律 SI，用 `pint` 校验；入库保留原始单位与换算记录。
- 报告结论必须标注证据等级与不确定度；无法给出结论时明确说「需要补什么数据/实验」，不要用模糊表述掩盖。
- 发现计划与现实不符时：先记录实测事实，再改 `WORKING_PLAN.md`，并在交付说明里指出改动点；不要静默偏离计划。

## 7. 当前决策状态

- **首个端到端目标器件：已由用户指定（2026-09-11）** —— `C:\Users\zmx\Desktop\b_GE_task3_2-new.mph`（98.9 MB）；
  另两个同名变体 `b_GE_task3_2-new  n7.mph`（528 MB）、`b_GE_task3_2-newyizu.mph`（4.25 GB）用于**参数化扫描**。
  已完成只读 probe（`work/reports/modelio/probe-*.json`），**尚未做基线求解、未做参数效验、未接入 `device_spec`**。
  即便如此，P0–P5 的内核仍必须**器件无关**：参数空间、性能指标、解析模型、验证阈值全部由声明式配置
  （`device_spec` / `task_spec`）提供，不得把该器件硬编码进内核。
- 实验数据：暂无 → 先建接入接口与「模拟实验闭环」。
- 算力：本机为主（实测 24 逻辑核、空闲内存 ≈22.5 GB —— **该值系 2026-09-11 实测，2026-09-14 复测已降至 ≈16.9 GB，随应用占用波动，勿当固定容量用**；**GPU 为 RTX 5070 Laptop 12 GB**，非旧文档的 RTX 3060 6 GB）；
  内存与提交限制的完整实测见第 3 节「内存 / 提交限制」行（commit limit 仅 37.1 GB 是本机跑 11 GB 级模型的真实约束）。
  MATLAB R2023b + COMSOL LiveLink 在位（`D:\matlab`、`D:\COMSOL64\Multiphysics\mli`）。
  另可借用服务器/集群 → 从第一天抽象 `ExecutionBackend`（`local` / `remote`），P0–P2 只实现 `local`。

## 8. 交付节奏：完成任务即同步到 GitHub（2026-10-14 用户指示）

**规则**：**每完成一个任务，就立刻把仓库同步到 GitHub**——不要攒到会话末尾或等用户催。

- **仓库与远端**：`origin` = `git@github.com:zmx20040302-afk/ai-.git`（**必须保持 private**，见第 2 节第 5 条与人保留放行权；仓库内含 DAC 2027 双盲投稿件与内部记录，**一旦转公开即构成匿名泄露**）。本机 `git` 在 `C:\Program Files\Git\cmd\git.exe`（不在 PATH 时用全路径）。
- **一律用 `scripts\git_sync.py` 提交**，不要手写 `git commit -m "中文…"`：本机是 Windows PowerShell 5.1，命令行里的中文会经控制台代码页损毁（本项目反复踩过）。`git_sync.py` 把提交信息写成 UTF-8 文件再 `git commit -F`，并在提交后**校验** `HEAD == origin/master` 且工作区干净。
  ```
  & work\.venv\Scripts\python.exe -X utf8 scripts\git_sync.py -m "简短标题" -b work/logs/COMMIT_MSG_<stamp>.txt
  ```
  （`-b` 给长正文文件；不给则只用标题。无改动时如实报「无需提交」，**不造假提交**。）
- **同步必须验证**，不能只看 `push` 退出码：脚本会 `git fetch` 后比对 `HEAD` 与 `origin/master`，并检查 `git status --porcelain` 为空；两者任一不满足即报失败。
- **提交信息要能自查**：写清「做了什么 / 验收结论 / 遗留与不主张」，数字必须来自产物（第 2 节第 1 条）。
- **注意 `work/` 不进版本库**（第 5 节）。因此 `work\dist\` 下的投稿包、`work\tools\` 下的生成器、`work\runs\` 下的证据**都不会**随提交上去；若某个交付物需要随仓库发布，必须先与用户确认改 `.gitignore` 或改落点，**不要**为了「更新成功」而静默放宽忽略规则。
