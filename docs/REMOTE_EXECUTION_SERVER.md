# 远端执行环境：实验服务器 `node01`（10.180.7.46）

> 本文记录**2026-10-03 实测**事实与踩坑，供 L1 网格收敛等重载求解任务使用。
> 裁决：服务器已批准为 L1 的正式执行环境之一 —— `feedback_id = fb-20261003-server_l1_env`
> （`backend=remote`、`pathway=ssh-comsolbatch`）。该裁决**不**构成 L1 通过，
> **不**改变模型状态，**不**授权在用户目录之外写入。

## 1. 通道与机器事实

| 项 | 实测值 |
|---|---|
| SSH 别名 | `ubuntu-10-180-7-46`（`~/.ssh/config` 已配；HostName `10.180.7.46`、User `zhangmx`、密钥 `~/.ssh/codex_ubuntu_10_180_7_46`） |
| 主机 | `hostname = node01`，Linux 6.8.0-31-generic |
| CPU | **96 核** |
| 内存 | MemTotal **394,877,072 kB ≈ 376 GB**；swap 122 GB（实测余 84 GB）；`/home` 15 T（余 5.6 T） |
| 用户授权工作目录 | `/home/lab/zhangmx/deepseek跑数据/`（中文名；见 §3 的传输注意） |
| 已有数据源（只读） | `/home/lab/projAI4US/autodesign/`（批 A/C 的 LiveLink 导出在此） |

**目标软件路径（实测）**：

| 用途 | 路径 / 命令 |
|---|---|
| COMSOL **6.4**（本项目用） | `/opt/software/comsol64/multiphysics`；启动器 `/usr/local/bin/comsol64` → `.../bin/comsol` |
| COMSOL 6.2 | `/opt/software/comsol62/multiphysics`；**`/usr/local/bin/comsol` 指向 6.2** ⚠️ |
| 编译 Java API 类 | **没有 `comsolcompile` 可执行文件**；用启动器子命令：`comsol64 compile X.java`（启动器支持 `…\|batch\|compile\|update\|…`） |
| 批处理执行 | `comsol64 batch -inputfile X.class -outputfile Y.mph -batchlog Z.txt -np N -stoptime S` |
| MATLAB | `/usr/local/bin/matlab`（R2024a），LiveLink 在 `…/comsol64/multiphysics/mli` |
| python3 | `/usr/bin/python3`（3.12.3），**无 numpy/scipy/torch/pandas**（要装需经 §5 的反向代理） |

⚠️ **`comsol` = 6.2，`comsol64` = 6.4**。要 6.4 就必须写 `comsol64`，否则会用到另一个大版本。

## 2. 提交—轮询模式（求解禁止并行扇出）

作业必须**脱离 ssh 会话**，否则掉线即被杀：

```bash
# 在远端 run 目录里：setsid + nohup，日志写文件
setsid nohup bash run_srv.sh > /dev/null 2>&1 < /dev/null &
```

`nohup ... &` 单独用**不够**（实测会话结束仍可能被带走）；`setsid` 先脱离控制终端再 `nohup`。
随后**只轮询日志**（不要用阻塞式等待）：`tail run_srv.log`、`grep -c FINISHED`、`pgrep -f`。

一次典型运行（四档 L1 阶梯）总耗时 **679 s**，峰值物理内存 **54.08 GB**。

## 3. 传文件：中文路径 + scp 的坑（都已实测）

1. **不要把中文路径交给 `scp`**：`/home/lab/zhangmx/deepseek跑数据/…` 经 PowerShell → `scp` 传参会
   被编码破坏（实测 `scp` 全部 `rc=1`）。做法：**先在远端用 shell glob 定位并复制到 ASCII 暂存区**，
   再从 ASCII 路径取回：

   ```bash
   for d in /home/lab/zhangmx/deepseek*/; do cp -f "$d"l1-x050-20261003/out.txt /home/lab/zhangmx/l1_x050_stage/out/; done
   ```
   ```powershell
   scp ubuntu-10-180-7-46:/home/lab/zhangmx/l1_x050_stage/out/out.txt .\srv_out.txt
   ```
2. **远端脚本不要用 PowerShell here-string 管进 `ssh`**：here-string 是 CRLF，`2>/dev/null` 会变成
   `/dev/null\r`，远端报 `Permission denied`（实测）。改为**写成 LF 文件再经 `cmd /c` 重定向**：

   ```powershell
   cmd /c "ssh -o BatchMode=yes ubuntu-10-180-7-46 bash -s < `"script.sh`""
   ```
3. **同名文件先核哈希**：服务器上 `/home/lab/projAI4US/autodesign/b_GE_task3_2-new.mph`
   是 394,181,144 B（sha256 `34085859150e7402…`），**与本机冻结的 103,681,293 B（`3efa34cc…`）不是同一个文件**。
   同名 ≠ 同文件；两侧 sha256 必须都算。

## 4. 时钟与资源礼仪

* ⚠️ **两机时钟不同步**：同一时刻服务器 `13:02`、本机 `14:25`（约 83 min 偏差）。**不要跨机比较时间戳**；
  用时以各自 `date -Is` / `elapsed` 为准。
* 资源占用是**动态**的，测试前先看：`uptime`、`free -g`、`pgrep -a -f comsol`。
  实测曾有他人 **COMSOL 6.2 GUI 占 ~208 GB RSS**、另一个导出批占 ~15 GB；
  照抄"某进程用了 208 GB"会**张冠李戴**（我第一次就把 GUI 的占用误记成导出批）。
* **必须记录 `-np`**：内存与耗时强依赖线程数（同一 ×0.7 档，本机默认线程 ~13 GB，服务器 `-np 16` **28.4 GB**）
  ⇒ 内存/耗时**不可跨配置比较**，数值可以。
* 我们的作业用 `-stoptime` 设硬上限，避免异常情况长期占机。

## 5. GPU 与网络（都已实测，避免误用）

* **2× NVIDIA A100-SXM4-80GB**，CUDA 12.8。但 `/usr/local/bin/comsol64-gpu0|gpu1` 只是
  VirtualGL 包装（`vglrun -d egl0 … -3drend ogl`）⇒ **是显示/渲染路径，不是求解加速路径**。
* 服务器**无直接外网**：本机用 `~/.ssh/keep-codex-proxy-tunnel.ps1` 反向转发
  `-R 127.0.0.1:7897:127.0.0.1:7897`，服务器经本机代理上网（装 pip 包前先确认隧道在跑）。

## 6. 许可（合规提示，事实照登）

`/opt/software/comsol64/multiphysics/license/license.dat` 与 6.2 对应文件的头部均为
`COMSOL CLIENT (LMCOMSOL) License File / TeAM SolidSQUAD-SSQ / 20.11.2025`，
条目形如 `FEATURE SERIAL LMCOMSOL 6.4 permanent uncounted`；`licenseinfo.ini` 记 `Name=hankx`。
**本机 Windows 的许可文件头部与之一致**。⇒ 这是项目环境的**既有**状况，技术上空闲席位不阻塞使用，
但**结果的投稿/对外发布合规性需由人判断**；不要在任何报告中把它描述为已授权的商业许可。

## 7. 复现一份远端 run 的最小步骤

```powershell
# 0) 本机：算好哈希（模型 + 驱动）
Get-FileHash work\runs\l1-solve-ladder-20261001\input.mph -Algorithm SHA256
# 1) 传到 ASCII 暂存区
scp work\runs\l1-solve-ladder-20261001\input.mph ubuntu-10-180-7-46:/home/lab/zhangmx/l1_x050_stage/
# 2) 远端：核哈希 → 移入工作目录 → 编译 → 起作业（见 §2/§3 的脚本）
cmd /c "ssh -o BatchMode=yes ubuntu-10-180-7-46 bash -s < stage_verify_compile.sh"
# 3) 轮询 → 完成后把产物复制到 ASCII 暂存区再取回 → 两侧哈希对账
```

完整实例（脚本、日志、哈希清单、分析产物）见
`work/runs/l1-x050-server-20261003/`（run `l1-x050-server-20261003`，29 个 artifact）。

## 8. LiveLink（MATLAB ↔ mphserver）的两个实测硬坑（2026-10-08 在 Stage-1 上踩到）

### 8.1 `plistarr` 用字符串设值会在**研究运行时**才炸

`model.study(tag).feature('param').set('plistarr', '0.2, 0.24, 0.28; 1; 8')`
——`set()` **不报错**，`getString()` 也能读回，但 `study.run()` 抛：

```
com.comsol.util.exceptions.FlException: Syntax error in expression.
  - Expression: {0.2, 0.24, 0.28; 1; 8}      ← COMSOL 把字符串包进 {} 当矩阵表达式解析
  - Subexpression: ; 1                       - Property: plistarr
```

实测（`stage1-20261008` 的 `setform_test.txt`，12 种形式逐个试）：
**任何含 `;` 的字符串形式都失败**，包括与模型原值同形的 `0.2, 0.24, 0.28; 1, 1, 1; 8, 8, 8`；
而 **cell 数组**形式成功：`set('plistarr', {'0.2, 0.24, 0.28', '1', '8'})`
（每个参数一个 cell，cell 内是逗号分隔的值列表；这正是该属性在 MATLAB 侧的天然表示——
对模型原值调 `getDoubleMatrix('plistarr')` 返回的就是 cell）。

**必须做预检**（否则要等求解启动才发现）：
```matlab
p.set('plistarr', {xstr, n1str, n2str});
m = p.getDoubleMatrix('plistarr');       % 与求解器同一条解析路径（getValidDoubleMatrix）
nPer = cellfun(@numel, m);               % 例如 [3 1 1] = x 三值、N1 一值、N2 一值
assert(isequal(nPer(:)', [numel(xList), numel(n1List), 1]));
```

### 8.2 标签数组是 `java.lang.String[]`，`cellstr()` 会失败

`model.study.tags()`、`model.param().varnames()`、`model.sol.tags()` 等返回
`java.lang.String[]`；`cellstr(...)` 报
`Conversion to cellstr from java.lang.String[] is not possible`。逐个转即可：

```matlab
function c = toCell(v)
    c = {}; n = numel(v); c = cell(1, n);
    for i = 1:n, c{i} = char(v(i)); end
end
```

### 8.3 一条通用纪律

**凡是"设了不报错、跑起来才炸"的属性，都要在求解前用与求解器同一条解析路径预检**
（本例 `getDoubleMatrix`）。这与 COMSOL 本机"静默失败 rc=15"是同一类风险的两个面：
**沉默的成功不可信，必须另找一条独立证据**（预检、回读、或最小执行）。

### 8.4 `getDoubleMatrix` 的**返回类型随形状而变**（2026-10-08 实测）

`plistarr` 这类"列表的列表"属性，`getDoubleMatrix` 的返回**不是固定类型**：

* **多个取值/参差**（如 `{'0.2, 0.24, 0.28', '1', '8'}`）⇒ 返回 **cell**（每参数一格）；
* **单值**（如 `{'0.2', '1', '8'}`）⇒ 返回 **3×1 的 double 矩阵**。

因此预检代码必须分支处理，否则会在单值情形下崩（run `stage1_smoke_20261008_100213_3777861` 实测
`Input #2 expected to be a cell array, was double instead`）：

```matlab
m = p.getDoubleMatrix('plistarr');
if iscell(m)
    nPer = cellfun(@numel, m);
else
    d = double(m);                              % 已是 double 矩阵
    nPer = repmat(size(d, 2), 1, size(d, 1));   % 每行元素个数
end
assert(isequal(nPer(:)', want), 'plistarr 各参数取值个数不符');
```

**同理**：容器的 `remove` 也有坑——`ModelUtil.remove(tag)` 移除的是**模型**（对 sol 静默无效）；
`model.sol.remove` 才是解；但**移除 sol 会触发内部 dispose 链异常并连带破坏共享结果节点**
（`cpt2` 消失 ⇒ 之后一切 `Unknown feature. Tag: cpt2`）⇒ **多组合扫描一律采用"零移除 + 可复用数据集"**，
结果定位改用**按值身份键**（见 `docs/SOLVER_AUTOMATION_INTEGRATION_20261008.md` 的 R4）。

