# 页面文件调整 — 用户授权 + 变更前证据 + 执行步骤

- 日期：2026-09-14
- 授权：**用户明确批准**（会话内选择「批准：调大页面文件到 ≥12 GB」）
- 执行方：**必须是用户本人以管理员身份执行**。实测当前 DSH 进程
  `IsInRole(Administrator) = False` → 我无法修改，也不会尝试绕过或自行重启。
- 依据：`docs\TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md` §4、
  `TO_DEEPSEEK_HARNESS_LT2R0v2停止线裁定回复.md` §Q3/§5

---

## 1. 变更前证据（2026-09-14 实测）

```json
{
  "measured_at": "2026-09-14",
  "measured_by": "work/.venv python + PowerShell 5.1 (CIM / Get-Counter)",
  "process_is_admin": false,
  "automatic_managed_pagefile": true,
  "pagefile_name": "C:\\pagefile.sys",
  "pagefile_allocated_mb": 4873,
  "pagefile_current_usage_mb": 715,
  "pagefile_peak_usage_mb": 915,
  "explicit_pagefile_setting": null,
  "c_free_gb": 195.5,
  "commit_limit_mb": 37063.0,
  "committed_bytes_mb": 31899.7,
  "commit_available_mb_derived": 5163.3,
  "physical_ram_mb": 32189,
  "identity_check": "commit_limit_mb - pagefile_allocated_mb = 32190 ≈ physical_ram_mb -> limit = RAM + pagefile 分配"
}
```

> 注意：`committed_bytes` 本次读数 31,899.7 MB，比早先同日的 25,296 MB 高出约 6.6 GB
> （其他应用占用增长）。因此**当前**可用 commit 只有约 5.2 GB，已低于有人值守回退门禁的 13,500 MB。
> 这说明本机 commit 余量不仅小，而且**波动很大**——进一步支持先做页面文件调整。

## 2. 期望的变更后状态（可据此验证是否真的生效）

```text
commit limit 期望值 ≈ 32,190 + 12,288 = 44,478 MB
（依据：变更前实测 limit 37,063 = RAM 32,190 + 页面文件 4,873，等式在同一次读数内闭合）
```

若重启后 `commit limit` 仍在 37,000 MB 附近 → 变更**未生效**，不得据此放宽门禁。

## 3. 执行步骤（管理员身份，PowerShell 或 GUI 二选一）

### 方式一：GUI（推荐，最不易出错）

```text
Win+R → sysdm.cpl → 高级 → 性能「设置」→ 高级 → 虚拟内存「更改」
→ 取消勾选「自动管理所有驱动器的分页文件大小」
→ 选中 C: → 选「自定义大小」→ 初始大小 12288 MB、最大值 12288 MB → 设置 → 确定
→ 按提示重启
```

### 方式二：管理员 PowerShell

```powershell
# 必须在「以管理员身份运行」的 PowerShell 里执行
$cs = Get-CimInstance Win32_ComputerSystem
Set-CimInstance -InputObject $cs -Property @{AutomaticManagedPagefile=$false}

$name = 'C:\pagefile.sys'
$pf = Get-CimInstance Win32_PageFileSetting -Filter "Name='C:\\pagefile.sys'"
if ($pf) {
    Set-CimInstance -InputObject $pf -Property @{InitialSize=12288; MaximumSize=12288}
} else {
    New-CimInstance -ClassName Win32_PageFileSetting -Property @{
        Name=$name; InitialSize=12288; MaximumSize=12288 }
}
# 然后重启
```

**取 12288 / 12288（固定 12 GB）的理由**：12 GB 是用户批准的**下限**，固定大小最可预测；
`MaximumSize` 不设更大值是为了不「静默扩大资源上限」（后继执行令明确禁止）。
若日后需要更大上限，应重新走一次授权，而不是悄悄放大。

## 4. 重启后请让我做（或你自己核对）的验证

```powershell
Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile
Get-CimInstance Win32_PageFileUsage   | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage
(Get-Counter '\Memory\Commit Limit').CounterSamples[0].CookedValue / 1MB
(Get-Counter '\Memory\Committed Bytes').CounterSamples[0].CookedValue / 1MB
Get-PSDrive C | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}
```

判定：

```text
AutomaticManagedPagefile = False
AllocatedBaseSize        = 12288 MB
commit limit             ≈ 44,478 MB（若仍 ≈37,000 → 未生效，不得放宽门禁）
C 盘可用空间              ≥ 12 GB + 余量（变更前 195.5 GB，预期减少约 7.4 GB）
```

## 5. 之后的动作（按裁定 §5 / §Q3）

1. 用**新 run-id** 对 `(0.8, 2)` 再做一次 7 频点资源确认；
2. 该次资源确认中 commit 先采用 `commit_warning <= 6144 MB` / `commit_hard_stop <= 4096 MB`
   （连续 2 个采样），预计调整后正常最低值约 7.7 GB，高于预警线；
3. 通过条件至少：`rows = 7`、`gaps > 15 s = 0`、三条硬线均未触发、`server cleanup = ok`、
   端口 30 s 内关闭；
4. 资源确认完成后，**再按新的实测最小值更新门禁**，不得静默放宽。

> **我不会自行重启系统**：重启会中断本会话与正在进行的实现工作。
> 请你选一个方便的时间执行 §3 并重启，重启后告诉我，我接着做 §4/§5。
