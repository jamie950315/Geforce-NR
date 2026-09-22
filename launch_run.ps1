param([Parameter(Mandatory=$true)][string]$RunArgs)
$ErrorActionPreference = 'Stop'
$name = 'GFN-Codex-Live-Run-20260921'
if ((Get-ScheduledTask $name).State -eq 'Running') { throw 'Existing run preserved' }
$action = New-ScheduledTaskAction -Execute 'C:\Users\jamie\dev\gfn-nr-core\.venv\Scripts\pythonw.exe' -Argument ('C:\Users\jamie\dev\gfn-codex-live-20260921\live_run.py ' + $RunArgs)
Set-ScheduledTask -TaskName $name -Action $action | Out-Null
Start-ScheduledTask -TaskName $name
Write-Output 'DISPATCHED; inspect the run outcome before claiming completion.'
