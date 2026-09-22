param([string]$ProbeArgs = '')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$name = 'GFN-HUD-Guard-UI-Probe'
$old = Get-ScheduledTask $name -ErrorAction SilentlyContinue
if ($old -and $old.State -eq 'Running') { throw 'Existing UI probe is preserved' }
$principal = (Get-ScheduledTask 'GFN-Codex-Live-Run-20260921').Principal
$python = Join-Path (Split-Path $root -Parent) 'gfn-nr-overlay\.venv\Scripts\pythonw.exe'
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + (Join-Path $root 'daily_ui_probe.py') + '" ' + $ProbeArgs) -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask $name
Start-Sleep -Seconds 2
for ($attempt = 0; $attempt -lt 10 -and (Get-ScheduledTask $name).State -eq 'Running'; $attempt++) {
    Start-Sleep -Milliseconds 500
}
if ((Get-ScheduledTask $name).State -eq 'Running') { throw 'UI probe still running' }
Get-Content (Join-Path $root 'daily-probe.json')
if ((Get-ScheduledTaskInfo $name).LastTaskResult -ne 0) { throw 'UI probe failed' }
