param([string]$ProbeArgs = '')
$ErrorActionPreference = 'Stop'
$name = 'GFN-Codex-Live-Probe-20260921'
$action = New-ScheduledTaskAction -Execute 'C:\Users\jamie\dev\gfn-nr-overlay\.venv\Scripts\pythonw.exe' -Argument ('C:\Users\jamie\dev\gfn-codex-live-20260921\desktop_probe.py ' + $ProbeArgs)
Set-ScheduledTask -TaskName $name -Action $action | Out-Null
Start-ScheduledTask -TaskName $name
Start-Sleep -Seconds 4
$info = Get-ScheduledTaskInfo $name
if ((Get-ScheduledTask $name).State -eq 'Running') { throw 'Desktop probe is still running' }
if ($info.LastTaskResult -ne 0) { throw "Desktop probe failed: $($info.LastTaskResult)" }
$neutral = New-ScheduledTaskAction -Execute 'C:\Users\jamie\dev\gfn-nr-overlay\.venv\Scripts\pythonw.exe' -Argument 'C:\Users\jamie\dev\gfn-codex-live-20260921\desktop_probe.py'
Set-ScheduledTask -TaskName $name -Action $neutral | Out-Null
Get-Content 'C:\Users\jamie\dev\gfn-codex-live-20260921\desktop.json'
