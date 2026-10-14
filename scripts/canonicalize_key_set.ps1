param(
  [Parameter(Mandatory=$true)][string]$Csv,
  [string]$Out = "",
  [string]$DatasetIn = "",
  [string]$BatchIn = "",
  [string]$N2In = "",
  [string]$SideColumn = "",
  [string]$SideValue = "",
  [switch]$QuarantinedFalse
)
# ---------------------------------------------------------------------------
# Implementation W: end-to-end re-canonicalization of a COMBINATION-KEY SET
# from the source CSV, hashed by two independent engines over the SAME bytes.
#
# This file is intentionally 100% ASCII (PowerShell 5.1 needs UTF-8 WITH BOM
# only when non-ASCII text is present) and param() is the first statement.
#
# Multi-value filters are PIPE separated ("A|C", "5.0|6.0|7.0") on purpose:
# a comma separated command-line token binds to a [string[]] parameter as ONE
# string (measured), which silently selects nothing.
#
# Frozen canonical rule (identical wording to scripts/collection_content_hashes.py):
#   render each element as a token "%.17g|%.17g|%.17g" of
#   (round(x_scale,6), N_w_te1, N_w_te2), sort ascending by the numeric triple,
#   append one "\n" after every token (exactly one trailing newline;
#   empty set = zero bytes), encode UTF-8 (no BOM), sha256.
#
# Hashing: in-memory System.Security.Cryptography.SHA256 over the UTF-8 bytes,
# cross-checked against certutil (Windows CNG) on a temp file. -Out is best
# effort (audit only; the run does not depend on it).
#
# stdout (last line): one JSON object
#   {"sha256":..,"selected":..,"unique":..,"chars":..,"bytes":..,"emit":"sha256"}
# Diagnostics -> stderr.
# ---------------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
$Inv = [System.Globalization.CultureInfo]::InvariantCulture

function Split-Pipe([string]$s) {
  if ($null -eq $s -or $s -eq "") { return @() }
  return @($s.Split('|') | Where-Object { $_ -ne "" })
}
$dsList = Split-Pipe $DatasetIn
$bList  = Split-Pipe $BatchIn
$n2List = Split-Pipe $N2In

$rows = Import-Csv -Path $Csv -Encoding UTF8
$sel = New-Object System.Collections.ArrayList
foreach ($r in $rows) {
  if ($dsList.Count -gt 0) {
    $v = [string]$r.source_dataset
    if (-not ($dsList -contains $v)) { continue }
  }
  if ($bList.Count -gt 0) {
    $v = [string]$r.batch
    if (-not ($bList -contains $v)) { continue }
  }
  if ($n2List.Count -gt 0) {
    $n2v = [double]$r.N_w_te2
    $hit = $false
    foreach ($t in $n2List) { if ($n2v -eq [double]$t) { $hit = $true; break } }
    if (-not $hit) { continue }
  }
  if ($SideColumn -ne "") {
    $v = [string]$r.$SideColumn
    if ($v -ne $SideValue) { continue }
  }
  if ($QuarantinedFalse) {
    $q = ([string]$r.quarantined).Trim().ToLower()
    if ($q -eq "true") { continue }
  }
  [void]$sel.Add($r)
}

$items = New-Object System.Collections.ArrayList
foreach ($r in $sel) {
  $x  = [math]::Round([double]$r.x_scale, 6)
  $n1 = [double]$r.N_w_te1
  $n2 = [double]$r.N_w_te2
  $tok = $x.ToString('G17', $Inv) + '|' + $n1.ToString('G17', $Inv) + '|' + $n2.ToString('G17', $Inv)
  [void]$items.Add([pscustomobject]@{ X = $x; N1 = $n1; N2 = $n2; Tok = $tok })
}

# numeric ascending by the triple, then stable de-duplication by token
$sorted = $items | Sort-Object X, N1, N2
$seen = New-Object 'System.Collections.Generic.HashSet[string]'
$sb = New-Object System.Text.StringBuilder
$nKeep = 0
foreach ($it in $sorted) {
  if ($seen.Add($it.Tok)) {
    [void]$sb.Append($it.Tok)
    [void]$sb.Append("`n")
    $nKeep = $nKeep + 1
  }
}

$enc = New-Object System.Text.UTF8Encoding($false)   # no BOM
$bytes = $enc.GetBytes($sb.ToString())

# --- engine 1: managed .NET SHA256 (in memory) ---
$sha = [System.Security.Cryptography.SHA256]::Create()
$h1 = ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join ''

# --- engine 2: certutil (Windows CNG) over a temp file holding the same bytes ---
$tmp = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllBytes($tmp, $bytes)
$certOut = & certutil -hashfile $tmp SHA256 2>&1 | Out-String
Remove-Item $tmp -Force -ErrorAction SilentlyContinue
$m = [regex]::Match($certOut, '[0-9a-fA-F]{64}')
$h2 = "<certutil-parse-failed>"
if ($m.Success) { $h2 = $m.Value.ToLower() }

if ($h1 -ne $h2) {
  [Console]::Error.WriteLine("ENGINE MISMATCH: dotnet=$h1 certutil=$h2")
  exit 3
}

if ($Out -ne "") {
  try { [System.IO.File]::WriteAllText($Out, $sb.ToString(), $enc) }
  catch { [Console]::Error.WriteLine("best-effort -Out write failed: " + $_.Exception.Message) }
}

$res = [pscustomobject]@{
  sha256   = $h1
  selected = $sel.Count
  unique   = $nKeep
  chars    = $sb.Length
  bytes    = $bytes.Length
  emit     = "sha256"
}
[Console]::Error.WriteLine(("selected={0} unique={1} bytes={2} engines=2" -f $sel.Count, $nKeep, $bytes.Length))
Write-Output ($res | ConvertTo-Json -Compress)
exit 0
