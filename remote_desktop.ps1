param([string]$ProbeArgs = '')
$ErrorActionPreference = 'Stop'
$name = 'GFN-Codex-Live-Probe-20260921'
$root = $PSScriptRoot
$python = Join-Path (Split-Path $root -Parent) 'gfn-nr-overlay\.venv\Scripts\pythonw.exe'
$entry = Join-Path $root 'desktop_probe.py'
if (!(Test-Path -LiteralPath $python -PathType Leaf) -or !(Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw 'The desktop probe or overlay Python runtime is missing'
}
if ((Get-ScheduledTask $name -ErrorAction Stop).State -eq 'Running') { throw 'Existing desktop probe is preserved' }
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '" ' + $ProbeArgs) -WorkingDirectory $root
Set-ScheduledTask -TaskName $name -Action $action | Out-Null
Start-ScheduledTask -TaskName $name
Start-Sleep -Seconds 4
$info = Get-ScheduledTaskInfo $name
if ((Get-ScheduledTask $name).State -eq 'Running') { throw 'Desktop probe is still running' }
if ($info.LastTaskResult -ne 0) { throw "Desktop probe failed: $($info.LastTaskResult)" }
$neutral = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '"') -WorkingDirectory $root
Set-ScheduledTask -TaskName $name -Action $neutral | Out-Null
Get-Content (Join-Path $root 'desktop.json')
