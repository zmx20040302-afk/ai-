# 常驻 Web 服务（对话控制台 / 静态看板）

> 记录日期：2026-09-24 ｜ 触发原因：DSH 重启把两个服务一起杀掉了（见 §1）
>
> **2026-09-29 更新（控制台 v2）**：控制台已升级为**显式双模式（离线 / DeepSeek）**并集成
> **响应级代理全部功能 + 数据浏览 + 内联 SVG 出图**。要点见本文 **§9**；
> 详细契约与指纹见 `docs/INDEX-records-and-rulings.md` §66。

## 1. 为什么要"脱离"启动

DSH 会把它启动的后台作业进程放进自己的 Windows **Job 对象**。
**DSH 一重启，Job 对象被拆，里面的所有子进程被一起终止**——实测：

| 时间 | 事件 |
|---|---|
| 2026-09-24 14:34:04 | DSH（`node …dsh/lib/bin.js web --port 3080`）被重启，进程是**新的** |
| 同一时刻 | 原 `pwsh-1`（8899 看板）与 `pwsh-4`（8877 控制台）**同时**被终止 |

两个作业的收尾状态：

* `pwsh-4`：`killed`，子进程报 `Windows Job runner exited with exit code 1073807364`
  —— `1073807364 = 0x40010004 = DBG_TERMINATE_PROCESS`（被终止机制结束，Job 拆解即此症状）；
* `pwsh-1`：`exit code 1`（Windows 上被强杀就是这个码，**没有** signal 标记，属中断而非命令失败）；
* 机器**没有**重启（`LastBootUpTime` 显示已连续运行 42 小时）。

⇒ 只要服务挂在 DSH 的作业对象里，**每次 DSH 重启都要手动重拉**。

## 2. 脱离手段：WMI 创建进程

用 **WMI `Win32_Process.Create`** 启动。进程由 `WmiPrvSE.exe` 创建，
**父链指向 Windows 服务而不是 DSH**，而 Windows 的 Job 成员资格是**从创建者继承**的
⇒ 新进程不在 DSH 的 Job 里，DSH 重启不再影响它。

**不要用 `Start-Process`**：它仍在当前 Job 内，会被一起杀。

实测父链（`python ← python(venv) ← cmd ← WmiPrvSE ← svchost ← services.exe ← wininit.exe`）：

```
[0] python.exe  pid=42028            <- 监听 8877
[1] python.exe  pid=30628            <- venv 解释器
[2] cmd.exe     pid=18632  cmd.exe /c "...\serve_console.cmd"
[3] WmiPrvSE.exe pid=8832            <- Windows 服务
[4] svchost.exe pid=1784
[5] services.exe
```

**DSH 的 node 进程（33248 / 47292）不出现在链上**——这就是"脱离"的判据。

## 3. 用法（**按需启动，非常驻**）

### 3.1 要用的时候：一个入口

```powershell
# 方式 A：双击（推荐，不用记命令）
work\tools\start_web_services.cmd

# 方式 B：命令行
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\serve_detached.ps1 -Action start
```

| 服务 | 端口 | 地址 | 日志 |
|---|---|---|---|
| 对话控制台 | 8877 | http://127.0.0.1:8877/ | `work/logs/webapp-8877.log` |
| 静态看板 | 8899 | http://127.0.0.1:8899/ | `work/logs/dashboard-8899.log` |

启动后**窗口可以直接关掉**——服务已脱离启动它的进程（见 §2），关窗不影响。

### 3.2 不要了的时候

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\serve_detached.ps1 -Action stop
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\serve_detached.ps1 -Action status   # 查状态
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\serve_detached.ps1 -Action restart  # 换端口/改启动器后用
```

### 3.3 当前默认策略：**不常驻**

**没有**登录自启、**没有**定时任务、**没有**守护进程。因此：

| 事件 | 需要动作吗 |
|---|---|
| **DSH 重启 / 换会话** | **不需要**（已脱离 DSH 的 Job 对象，§2）——**如果你之前已经启动过，它还在跑** |
| 机器重启 / 注销重登 | **需要**（跑一次 §3.1；没有自启） |
| 服务自己崩了 | **需要**（没有守护） |
| 想让它一直可用 | 见 §3.4（可选，默认**不装**） |

### 3.4 可选：如果你哪天想改回"常驻"

```powershell
$I = 'scripts\install_web_services_task.ps1'
powershell -NoProfile -ExecutionPolicy Bypass -File $I -Action install   # 登录自启 + 每 15 分钟自愈
powershell -NoProfile -ExecutionPolicy Bypass -File $I -Action show
powershell -NoProfile -ExecutionPolicy Bypass -File $I -Action remove    # 卸载
```

装出来两样东西（动作都是幂等的 `-Action start`，端口已在监听就跳过）：

| 组件 | 作用 | 位置 |
|---|---|---|
| 计划任务 `MEMS-Harness-Web` | **每 15 分钟**幂等自愈（也覆盖重启后的恢复） | 任务计划程序根目录（当前用户级） |
| 登录自启入口 `MEMS-Harness-Web.cmd` | **登录时**立即拉起 | `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` |

⚠️ 装上之后 `-Action stop` **只是临时的**（最多 15 分钟被拉回）；要长期停必须 `-Action remove`。

### ⚠️ 权限实测（决定了这套东西为什么必须分成两条路）

| 注册方式 | 结果 |
|---|---|
| `Register-ScheduledTask` + `New-ScheduledTaskTrigger -AtLogOn` | ❌ **Access is denied**（`0x80070005`） |
| `schtasks /create /sc onlogon` | ❌ **ACCESS DENIED**（登录触发器影响所有用户，需管理员） |
| `Register-ScheduledTask`（不含登录触发器） | ❌ 同样 Access is denied |
| **`schtasks /create /sc minute /mo 15`** | ✅ **SUCCESS**（当前用户级，无需管理员） |

⇒ 安装脚本走**可行的那条**：定时任务用 `schtasks /sc minute`，
登录自启用**当前用户启动文件夹**。若你要原生"登录触发器"任务，
用**管理员** PowerShell 跑一次 `-Action install`（脚本里有说明）。

### 实测记录

* **2026-09-24 冷启动**：先 `-Action stop` 停掉两个服务（确认端口不再监听），
  再 `Start-ScheduledTask`（等价于定时触发）⇒ 两个服务**都起来了**且 `200`
  （8877 → `200 11184B`，8899 → `200 30529B`）。
* **2026-09-25 按需启动**：走 `work/tools/start_web_services.cmd`（模拟双击）⇒ 两个服务起来且 `200`；
  **70 秒后复查 PID 不变**（确认不会自己消失）；父链为
  `python ← python(venv) ← cmd ← WmiPrvSE ← svchost ← services.exe`，**DSH 的 node 不在链上**。
* **2026-09-25 09:32 机器重启**：重启前跑着的服务随之消失——这正是"不常驻"策略下的预期行为
  （要恢复就跑 §3.1；若不想手动，装 §3.4）。

## 4. 注意事项

* **脱离后在 DSH 的 jobs 列表里看不到它们**——用 `-Action status` / `-Action stop` 管理，
  不要以为"jobs 里没有 = 没在跑"。
* **日志**：`work/logs/webapp-8877.log`、`work/logs/dashboard-8899.log`（**追加**写，长期跑要留意体积）。
* **不再有任何自动拉起**（默认策略，§3.3）：重启/崩溃后需要手动跑 §3.1。
* **仍然只绑 127.0.0.1**，不对外暴露；服务进程的 stdout 已重定向，不再依赖 DSH 的作业管道。
* 端口被占用时 `-Action restart` 会先终止占用者（`Stop-Port` 带超时轮询等待端口释放）。

## 5. 两个编码/语法坑（已写成用例，见 `tests/test_web_services_detached.py`）

1. **`.ps1` 必须 UTF-8 with BOM**：PowerShell 5.1 对无 BOM 脚本按 ANSI/GBK 解码，
   中文注释会变乱码并触发解析错误。
2. **`param()` 必须是脚本第一条语句**：本文件初版在开头用了 Python 风格的 `"""…"""`
   文档串，PowerShell 把它当表达式 ⇒ 报 `param : The term 'param' is not recognized`。
   PowerShell 的块注释是 `<# … #>`。

用例同时锁住：`.cmd` 必须纯 ASCII（cmd.exe 按 OEM 代码页读）、端口与启动脚本名在 `.ps1`/`.cmd` 间一致、
代码体里不得出现 `Start-Process`。

## 6. 控制台 v2（2026-09-29）：显式双模式 + 代理全部功能

| 项 | 内容 |
|---|---|
| URL | **`http://127.0.0.1:8877/`**（页面本体在 `scripts/webapp_page.html`，启动时读入并校验措辞） |
| **工作模式** | 右上角开关：**离线模式**（默认）/ **连接 DeepSeek**。默认**绝不上网**——即使服务端已有凭据 |
| 离线模式 | 全部功能可用（纯本地计算）；对话框**降级为本地关键词路由**，回答明确标注「非 LLM 生成」 |
| DeepSeek 模式 | 用服务端凭据（`DEEPSEEK_API_KEY` 或 `~/.dsh/.credentials.yaml`）；**密钥绝不下发前端**；**LLM 不参与裁决** |
| 侧栏分区 | 对话 / 模型卡 / 预测 / 覆盖与拒答 / 两点对比 / DOE 预筛 / 一致性哨兵 / 平台任务 / 数据浏览 |
| 出图 | 全部**内联 SVG**（无外部 CDN，离线可用）：频谱+双误差带、覆盖条形图、预筛散点图 |
| 自检 | `python -B scripts\webapp_server.py --selftest` → 14/14 |

### 6.1 页面上的硬性提示（**不得删除**）

页面源码里写死：「响应级代理（**不是 AI 求解器**）：没有场数据 ⇒ **无场级误差界**；
没有 L1 网格收敛 ⇒ **不给工程绝对值**；每次预测强制带 `model_id`、认证区间与**拒答判定**；
状态只能是 `draft_surrogate`，**放行权在人**」。缺任一条 ⇒ **服务端拒绝启动**。

### 6.2 后期开局域网（一步即可）

```powershell
python -B scripts\webapp_server.py --host 0.0.0.0 --port 8877 --token <至少16字符>
```

* 设了 `--token` 后**所有端点**都要带 `Authorization: Bearer <token>` 或 `?token=<token>`；
* **非回环地址不带 `--token` 会直接拒绝启动**——本控制台能在本机跑**写产物**任务，
  裸暴露等于把写权限交出去（fail-closed）。

### 6.3 常用端到端自检

```powershell
# 页面与必备声明
curl.exe -s http://127.0.0.1:8877/ | findstr /C:"不是 AI 求解器"
# 模式（应为 offline 且 network_allowed=false）
curl.exe -s http://127.0.0.1:8877/api/mode
# 代理预测（拒答域内应 refused=true 且不含任何数字）
curl.exe -s -X POST http://127.0.0.1:8877/api/surrogate/predict -H "Content-Type: application/json" -d "{\"x\":0.20,\"N1\":1,\"N2\":8}"
```

### 6.4 **改前端后必跑的三件检查**（2026-09-29 新增）

"点按钮没反应"这类故障**不能靠人点**去发现。三条命令按顺序跑：

```powershell
# ① 静态：JS 引用的每个 $('#id') 必须存在、无重复 id、按钮都绑过、措辞齐全
python -B work\tools\check_page_ids.py
# ② 语法：把页面 JS 抽出来交给真 JS 解析器（会吃 Python 转义那层）
python -B work\tools\check_page_js.py
node --check work\tmp_page.js
# ③ 真浏览器跑一遍（走**真实 click** 通道）
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
  --virtual-time-budget=20000 --dump-dom "http://127.0.0.1:8877/?run=predict&x=0.55&N1=1&N2=6" `
  > work\logs\dom_predict.html
python -B work\tools\inspect_page_dom.py work\logs\dom_predict.html pred
```

还有一个 Node 侧的运行时探针（记录事件绑定并**调用**处理器，能直接回答"处理器绑上了吗"）：

```powershell
node work\tools\page_runtime_check.mjs
```

### 6.5 可分享链接（也用于自动化）

```
http://127.0.0.1:8877/?run=predict&x=0.55&N1=1&N2=6&alpha=0.10
http://127.0.0.1:8877/?run=coverage
http://127.0.0.1:8877/?run=screen&n2=9&n1max=6
http://127.0.0.1:8877/?run=sentinel&x=0.55&N1=1&N2=6
http://127.0.0.1:8877/?run=data
```

`run` 可选 `predict` / `coverage` / `compare` / `screen` / `sentinel` / `data`；
页面加载后**自动点击对应按钮**（与人工点击同一条代码路径）。

### 6.6 排障：页面"点了没反应" / "打不开"

**① 最常见：服务其实已经不在跑了**（2026-09-29 实际踩到）。先跑这一条：

```powershell
python -B work\tools\verify_web_services.py --port 8877 --settle 150
```

它会做两轮（相隔 150 秒）检查：端口在听、首页与磁盘页面**逐字节一致**、`no-store`、
默认离线、预测接受例带 `model_id/certified/区间`、拒答例不含任何数字。
**两轮都过才算通过** —— 因为"启动成功" ≠ "持续可用"。

**② 一键打开（推荐给日常使用）**：双击 `work\tools\open_console.cmd`
—— 它会先探测、没跑就启动、**等 HTTP 真的应答**、再打开默认浏览器。

**②′ 桌面快捷方式（2026-10-01 新增）**：桌面上的「启动 MEMS 控制台」指向**同一个**
`work\tools\open_console.cmd`（不是直接开 URL）⇒ 双击后：探测 → 没跑才启动 →
等到 API 真应答 → 才开页面。重建 / 改名 / 删除都用同一个脚本（幂等、默认不覆盖）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_desktop_shortcut.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_desktop_shortcut.ps1 -Name "我的控制台" -Force
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_desktop_shortcut.ps1 -Remove
```

安装器保存后**回读 `TargetPath` 并断言它等于预期启动器**（只检查"文件在"不够）；
不变量由 `tests/test_desktop_shortcut.py` 锁住（含中文 ⇒ .ps1 必须 **UTF-8 with BOM**、
仓库根从 `$PSScriptRoot` 推导、默认拒绝覆盖、目标必须是那个自愈启动器）。

**③ 硬刷新**（`Ctrl+F5`）：HTML 已改为 `Cache-Control: no-store`，但升级前缓存的旧页
仍可能留在浏览器里，表现为"按钮不存在/点了没反应"。

**④ 页面顶部 `#errBanner`**：任何 JS 异常都会显示在那里（不再静默）。

**⑤ 服务端也会"一直发旧页"（2026-09-30 实测，与 ③ 是不同的两件事）**：
`scripts/webapp_server.py` 里是 `PAGE = _load_page()` —— 页面在 **import 时读一次**，
之后**不再读盘**。实测：磁盘上的 `webapp_page.html` 已是 **97,627 B**（含新的「数据字典」分区），
而运行中的 8877 仍稳定返回 **92,488 B** 的旧页 ⇒ 用户看到的是"新分区根本不存在"。
`Cache-Control: no-store`（③）只解决**浏览器**的启发式缓存，**管不到服务端这一次读**。
⇒ 改完前端必须 `& scripts\serve_detached.ps1 -Action restart`，然后按 §6.6 跑**两轮**复检
（§6.7 的纪律：`restart` 会杀掉上一个实例，通知用户前必须复检）。
*可选改进（未实施）*：把发送路径改成按 mtime 重读；难点是"新页校验不过时该发旧页还是报错"
需要口径，故留给用户拍板，不擅自改服务端语义。

### 6.7 ⚠️ 运维纪律（**用 `-Action start`，不要随手 `-Action restart`**）

`restart` = 先杀端口上的进程再启动。**每次 `restart` 都会终止上一个实例**。
2026-09-29 的教训：我为了验证连续调了几次 `restart`，最后一次 kill 之后**没有复检**就通知用户打开，
结果用户去开时端口已关 —— 现象是"页面打不开"且"预测失败"（请求没有服务端可打）。
⇒ **规则**：给用户 URL 之前，必须用 §6.6 的 `verify_web_services.py --settle` 复检；
日常只需 `-Action start`（**幂等**：端口已在监听就跳过）。

### 6.8 ⚠️ 脱离 Job ≠ 免疫控制台事件（2026-10-01 实测并修复）

**事故**：用户在用的控制台**整个停了**（8877/8899 都无人监听、无相关 python 进程）。
`work/logs/webapp-8877.log` 尾部：一条 `starting webapp_server on 8877`，紧接着一个**字面 `^C`**
—— 服务是被**控制台事件**（Ctrl+C / 窗口关闭）终止的，不是崩溃（没有 traceback）。

**根因**：`serve_detached.ps1` 用 WMI 创建 `cmd.exe /c serve_console.cmd`，而服务原本是在
**这个 cmd 的控制台里前台跑**。WMI 只解决"DSH 重启会拆 Job 带走子进程"（§1），
**完全不解决"控制台事件能打死控制台子进程"** —— 这是两件事，此前文档没有区分。

**修法**：两个启动器改用 **`pythonw.exe`（GUI 子系统、无控制台）**，经 `start /b /wait` 拉起：

```bat
set PYW=%REPO%\work\.venv\Scripts\pythonw.exe
if not exist "%PYW%" set PYW=%REPO%\work\.venv\Scripts\python.exe
start "" /b /wait "%PYW%" -B "%REPO%\scripts\webapp_server.py" --port 8877 >> log 2>&1
```

`start /wait` 保留"进程真的退出才写 `exited with N`"的语义（`ERRORLEVEL` 是子进程退出码）。

**验证（是实验，不是推断）**：重启后服务跑在 `pythonw.exe`；随后**杀掉两个启动器 `cmd.exe`**，
再发真 HTTP 请求 —— 8877 `/api/mode` **200**、8899 `/` **200** ⇒ 服务存活。
这正是原来会死的那个场景。`-Action status/stop` 本来就按**端口**判定，所以启动器死掉不影响检测与收尾。

**不变量已锁**：`tests/test_web_services_detached.py::test_service_launchers_use_a_consoleless_interpreter`
（必须有 `pythonw.exe`、`start "" /b /wait`、缺失时回退到 `python.exe`、端口与脚本名一致）。

---

## 10. 控制台 v3 新增能力（2026-09-29）

本次在 v2 基础上补了四项，**均已通过用例与两轮服务复检**。

### 10.1 多通道一阶峰代理端点

| 端点 | 说明 |
|---|---|
| `GET /api/mc/model` | 模型卡：`model_id`、状态、适用域、逐通道半宽与**已知短板** |
| `GET /api/mc/predict?x=&n1=&n2=&alpha=` | 预测（缺省三个正式目标）；`alpha` 只认 0.10/0.05/0.01 |

* 模型产物：`work/runs/multichannel-surrogate-20260929/multichannel_model.json`
  （**部署**用全部数据拟合；**评估**数字来自折——两者必须分开，混用即数据泄漏）；
* 加载时**双重校验**（自校验 `model_id` + 标签表哈希），被改动过就拒绝启动；
* ⚠️ **不是 AI 求解器**：只预测一阶峰标量，无场级误差界、无 L1；
* **拒答不返回任何数字**；§3.4 约束量（功率/应力/能量）**不在**可预测通道里。

### 10.2 子智能体（离线可点名）

| 端点 | 说明 |
|---|---|
| `GET /api/agents/list` | 9 个角色 + **离线能力边界**说明 |
| `POST /api/agents/payload` | 生成契约化载荷、落 append-only 台账、返回可复制 prompt |
| `GET /api/agents/ledger?tail=N` | 台账尾部（只读） |

**离线模式的边界（写在界面与返回里，不是藏在文档里）**：

* ✅ 能：列角色 → 按契约生成**可注入载荷**（契约原文逐字节）→ 落
  `work/role-spawns/spawn_ledger.jsonl` → 给可复制 prompt；
* 🚫 不能：**真正 spawn**。离线模式**绝不调用 LLM**——这是红线，不是功能缺失。
  真 spawn 要么把 prompt 注入 DSH 的 subagent，要么切 DeepSeek 模式（会联网）；
* 返回里带 `is_llm_involved: false`，便于审计"这一步没有模型参与"。

**测试钩子**：请求可带 `out_root` / `ledger_path`（服务端强制校验必须在 `work/` 下）。
页面上对应两个 **hidden input**（`#agOutRoot` / `#agLedgerPath`），留空即走真实台账；
自动化验证必须填它们，否则会往 append-only 的真实台账里写。

> ⚠️ **已知留痕**：`work/role-spawns/spawn_ledger.jsonl` 现有 3 行，其中
> `spawn-20260929T140739Z-*` 与 `spawn-20260929T140925Z-*` 是**本人在自动化验证时**点出来的
> （当时还没有 10.2 末尾那个测试钩子）。台账 append-only ⇒ **不删**，在此如实说明：
> **它们不是人工的角色点名**。后续自动化一律走 `out_root`/`ledger_path`。

### 10.3 任务超时与取消可见性

此前任务跑起来只能干等：看不出"跑了多久、额度多少、是不是已经卡住"。

* **执行改为子进程**（`--exec-task` 入口）：**线程无法被安全终止**，在线程里做超时只能"报告超时"
  而任务还在跑 —— 那种 `timed_out` **不可验证**；子进程可以被真正杀掉；
* 超时按任务配置（`TASK_TIMEOUTS`，缺省 **300 s**；`selfcheck` 900 s、`state` 120 s…），
  `GET /api/jobs` 会带上每个任务的 `timeout_s`，界面上按钮旁直接显示；
* `GET /api/tasks/active`：正在跑的任务给出 **已耗时 / 超时额度 / 剩余秒数 / pid**；
* `GET /api/job/<id>/cancel`：**真杀进程树**（Windows 用 `taskkill /PID <pid> /T /F`，
  必须带 `/T`：控制台任务自己常再起子进程，只杀直接子进程会留孤儿）；已在终态则**如实说"没有可终止的进程"**；
* 超时后状态是 `timeout`，**不产出结果**，并给出终止证据（命令 + 回码）；
* 台账 `work/logs/task_runs.jsonl`（append-only，含 `timed_out` 与 `verdict`），
  供事后审计"到底超时过几次"。`job_id: null` 表示不是从任务队列进来的（直接调用/测试）；
* ⚠️ **测试期不写生产台账**：`selfcheck` 任务会跑 pytest，而测试又会调任务 ⇒ 用
  `PYTEST_CURRENT_TEST` 把记录改道到临时目录（有用例锁住"台账行数不变"）。

### 10.4 MCP 侧（控制台作为被调用方）

新增 6 个 MCP 工具：`console_status` / `console_tasks` / `console_run_task` / `console_job` /
`monitor_model_card` / `monitor_predict`。

* **控制台是执行方，MCP 只做客户端**（走 HTTP，默认 `http://127.0.0.1:8877`，
  可用 `MEMS_CONSOLE_URL` / `MEMS_CONSOLE_TOKEN` 覆盖）。
  **为什么不在 MCP 进程内直接 import 控制台模块**：控制台用 `EXEC_LOCK` 把"写产物/写库"串行化，
  若 MCP 在另一个进程里直接调同一函数，就是**两把不同的锁** ⇒ 会出现两个任务同时写库/写产物，
  破坏"求解环节禁止并行"的约束；
* 控制台没在跑时**如实返回 `console_unavailable=true` 与启动方法**，不静默失败、也不绕过它；
* 写产物任务经 MCP 也必须 `confirm=true`（控制台会再拦一次，双重把关）；
* 工具集用**集合相等**断言锁住（`tests/test_mcp_new_tools.py::EXPECTED_TOOLS`），
  新增/改名必须显式改那里，避免"注册了但没人验证"。

---

## 11. 控制台 v4（2026-09-30）：**数据字典**分区（只解释，不计算）

用户要求原文：「再增加一个页面，讲解各个参数和计算结果，可以进行每个结果的系统介绍，
**不需要计算，只需要把每一个数据名称讲清楚**」。

| 端点 | 说明 |
|---|---|
| `GET /api/glossary` | 整包：`coverage`（逐表覆盖自检）+ `sections`（8 类共 65 条）+ `no_computation` 声明 |

* 页面：侧栏第 3 项「数据字典」（`p-gloss`）。筛选：搜索 / 类别 / 「只看参与排名的正式目标」。
* 每条给：**名字** · 中文名与单位 · **它是什么** · **口径/来源** · 方向与排名 · ⚠️ 坑 ·
  「表里也叫 ……」（原始表列名 → 规范名）；口径未书面确认的量带黄色 pill。
* **覆盖不变量**（`tests/test_glossary.py` 锁住，表缺失则 skip 而**不静默通过**）：
  真实表里 **109 个去重列名 / 0 处遗漏**；65 条解释 / 47 个别名；
  逐表 `multichannel_labels` 64/64、`A/points` 15/15、`A/power` 11/11、
  `A/mech` 16/16、`A/combos` 24/24、`B/source_table` 10/10。
* **同名不同表**：`v_z_m3s` 在 `A/power.csv`（全局声学域）与 `A/mech.csv`（结构域）**不是同一个量**
  ⇒ 用 `TABLE_ALIASES` 按表解析（覆盖率自检当场抓出来的真问题）。
* 「不做任何计算」写进载荷与页面，并由用例断言，防止这一页被悄悄改成"算给你看"。
* **改完页面必须重启控制台**（服务端 `PAGE` 只在 import 时读一次，见 §6.6 ⑤）。

---

## 12. 控制台 v5（2026-09-30）：**失败通道**（不能完成 → 可发送的分析包）

用户要求：「完善该页面，当出现无法完成的任务时可以发送过来进行分析和处理」。
口径由用户当场选定：**收全部失败面**、**只生成自包含包**、
**包内只放**「现象 + 原始错误全文（含堆栈）」与「当时的输入与调用（端点/参数/复现命令）」。

| 端点 | 说明 |
|---|---|
| `GET /api/incidents?limit=N` | 列表 + 分类计数 + 承诺声明（**包只落本机**）+ 台账路径 |
| `GET /api/incidents/one?incident_id=` | 单条 + 已渲染的 markdown（不落盘） |
| `POST /api/incidents/record` | 登记一条（未登记类别 **400**，并回 `valid_kinds`） |
| `POST /api/incidents/package` | `{incident_id, write:true}` → 落 `work/runs/incidents/`（首次生成才创建 ⇒ 若一次都没生成过则**不存在**）；**已存在即拒绝覆盖** |

**自动采集点**（8 个 kind：`task_timeout/task_failed/task_cancelled/refusal/page_error/api_error/service_unavailable/manual`）：

* 任务超时/失败 —— `_exec_task_child` 的非成功终态（**成功不登记**）；
* 任务取消 —— `cancel_job`（那里才有进程树终止证据；`_exec_task_child` 不重复登记）；
* 代理拒答 —— 多通道 `Refused` 异常 + 响应代理返回值里的 `refused: true` 两条路；
  **网格筛查只登记"整张网都不可预测"**（逐点拒答是正常结果，逐点登记会一次灌 153 条）；
* 接口未处理异常 —— `do_GET/do_POST` 外层包裹 ⇒ 回 500 并在台账留完整堆栈；
* 页面脚本异常 —— `#errBanner` 那条路顺手登记（同消息只报一次，每次开页上限 10 条）；
* 服务不可用 —— 页面 `fetch` 失败时入 `localStorage` 队列，连上后自动补登记
  （补登记那次请求禁止再入队，否则会自我繁殖）。

**刻意不采集**：MCP 侧看到 `console_unavailable` **不登记** —— 控制台"按需启动、不常驻"
是既定策略（§3.3），"没在跑"不等于故障。只有"人正在用页面、请求却没应答"才算失败。

**脱敏**（两条路，缺一条就漏）：按**参数名**判密钥（`token/key/secret/password/…` 整值替换）
＋ 按**文本模式**扫值（`sk-…`、`Bearer …`、`key=…`、`?token=…`）。脱敏在**入库前**做，
台账本身不留明文；`redacted_hits` 写进包，让接收方知道有东西被抹掉了。

**端到端核对**（**不会写生产台账**：自带临时控制台 + 台账/包目录重定向）：

```powershell
python -B work\tools\verify_incident_channel.py
```

它会验：拒答自动登记 → 任务失败自动登记 → 人工上报 → 包落盘 → 重复生成被拒 →
未登记类别 400 → **生产台账逐字节未变**。包内自带「不含分析结论、接收方判断不得改变
裁定或模型状态」的声明（红线 5）。

### 12.1 ⚠️ 例行复检会制造拒答 ⇒ 诊断方必须能声明「别登记」

**实测教训**：`verify_web_services.py` 每轮都跑一个域外预测用例（那是它的职责），
于是一次两轮复检就往生产台账塞了 **2 条 refusal**；`page_runtime_check.mjs` 同样会打域外用例。
这些**不是任何人遇到的问题**，却会把失败通道稀释成机器噪音。

⇒ 诊断方用下面任一方式**如实声明**自己不是人的操作：

| 方式 | 谁在用 |
|---|---|
| 请求头 `X-MEMS-No-Incident: 1` | `work/tools/verify_web_services.py` |
| 查询参数 `?no_incident=1`（`diag=1` 同义） | 页面：`?no_incident=1` 打开即为诊断模式，`api()` 自动带上该头并**关掉页面侧的自动上报** |
| 桩里 `location.search='?no_incident=1'` | `work/tools/page_runtime_check.mjs` |

**覆盖面是有限的，且写在这里**：只抑制**同步**采集（拒答、接口异常）。
任务类事件发生在工作线程里，thread-local 传不过去 ⇒ **仍然登记**
（任务失败本来就值得看）。**人工上报与生成分析包不受影响**（那是显式动作）。

验证：改完这个开关后，先跑两轮复检 + 页面探针（两者都会打拒答用例），
再查台账 ⇒ **台账不存在（一行都没有）**；同时 `verify_incident_channel.py` 仍能
正常记下真拒答 ⇒ 证明 opt-out 没有把功能一起关掉。

---

## 13. 控制台 v6（2026-09-30）：**上报给 DSH**（只读分析）

用户要求：「出现异常页面可以直接进行上报，**直接上报给 deep seek harness**」。
口径由用户当场选定，三条都是**代码门禁**（不是界面提示）：

| 口径 | 实现 |
|---|---|
| **只读分析**（给根因 + 修复建议，**不改仓库任何文件**） | 4 条硬约束逐条写进 prompt（`dsh_report.READONLY_RULES`），并要求输出「根因 / 还需什么证据 / 建议修复 / 不确定处」；用例断言这些文字确实在 prompt 里 |
| **只在人点按钮时**上报 | 没有任何自动触发路径；每次上报需 `confirm=true`，页面按钮先弹确认框 |
| **离线模式禁止** | `_dsh_start` 第一道门就是模式检查（**在查记录之前**，安全门禁不该被"记录不存在"绕过） |

**怎么做**：`POST /api/incidents/report_to_dsh` → 在本机启动一次
`dsh --profile headless <任务文本>`（DSH **自带**的一次性任务接口：跑完打印结果就退出，
不开端口、不留后台服务、共用同一套模型/工具/安全默认值）。
`GET /api/incidents/dsh_reports?incident_id=` 查进度与结论。
台账 `work/logs/dsh_reports.jsonl`（首次上报才创建 ⇒ 现在**不存在**）；
产物落 `work/runs/incidents/<id>/<report_id>/`（同前，首次上报才创建，现在不存在），
里面有 `prompt.md` / `stdout.txt` / 它自己可选的 `analysis.md`。

**为什么不是去调 DSH 的内部 RPC**：那要猜内部协议（本仓库明令不许猜内部）；
`headless` 是官方 bundle，README 明确它就是给脚本/CI 用的一次性任务入口。

**环境事实**：`dsh` **不在 PATH 上**（实测 `Get-Command dsh` 找不到）⇒ 解析顺序是
`DSH_BIN` 环境变量 → PATH → npx 缓存里**发现**（`_npx/*/node_modules/@deepseek-ai/dsh/lib/bin.js`）。
都找不到就**如实报错**并告诉用户设 `DSH_BIN`，**不猜路径**。

**防误触（实测被这条救过）**：`start_report(confirm_spawn=True)` 必须显式给 —— 2026-09-30
我写了个"只是组装 prompt"的冒烟测试，结果它**真的**把 headless DSH 拉起来、读 prompt、开始推理、
消耗 token。此后：① 无 `confirm_spawn` 一律拒绝；② `PYTEST_CURRENT_TEST` 下必须由 `DSH_BIN`
指定替身，**测试绝不许跑真 DSH**（`verify_incident_channel.py` 也一律用替身）。

---

## 14. 控制台 v7（2026-09-30）：失败改为**弹出式上报**（取消单独分区）

用户要求：「失败的时候界面可以**弹出错误上报按钮**，**不要单独的失败通道**……
**我选择是否进行上报**」。

| 项 | 现在 |
|---|---|
| 入口 | **没有**侧栏分区；顶栏一个「错误与上报」按钮（始终可见）+ 失败时**自动弹窗** |
| 弹窗 | 类别 + 现象 + 三个按钮：**上报给 DSH 分析** / 只生成分析包 / 忽略；并写明「上报与否由你决定 —— 这里不会自动上报」 |
| 触发 | 页面侧：`window 'error'` / `unhandledrejection` / `fetch` 失败 → 立即弹；服务端侧（任务失败/超时/取消、接口异常、代理拒答）：页面每 **12s** 拉 `/api/incidents?limit=20`，**新出现的**才弹（按 `incident_id` 去重） |
| 历史与人工上报 | 同一个**按需对话框**（`#incDlg`，顶栏按钮打开，Esc 关闭） |
| 不自动上报 | **代码约束**：`incDsh(` 只出现在弹窗的点击处理器里（有用例断言）；上报还要 `confirm=true` + 服务端模式门禁 |

**诊断请求现在**连**显式上报也不落库**（`?no_incident=1` 或 `X-MEMS-No-Incident`）：
实测探针点一次"人工上报"就会往生产台账塞一条「运行时探针……」记录。现在这种情况返回
`{"diagnostic": true}` 且**不写台账**。

**给运行时探针的钩子**：页面只暴露 `window.__memsPop`（触发一次弹窗）用于验证
"上报按钮真的弹出来"；"异常→弹窗"这条接线由 pytest 静态断言守着。

> ⚠️ `page_runtime_check.mjs` 的 DOM 桩必须与真浏览器对齐：本轮它缺
> `document.addEventListener`，导致页面里那行 `keydown` 绑定抛错，**连带后面 4 个按钮全部未绑定**
> （表现像"页面坏了"，其实是桩不全）。同类假失败已是第三次 —— 改桩时先怀疑桩。


