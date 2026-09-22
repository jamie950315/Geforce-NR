$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path (Split-Path $root -Parent) 'gfn-nr-core\.venv\Scripts\pythonw.exe'
$script = Join-Path $root 'daily_ui.py'
if (!(Test-Path $python) -or !(Test-Path $script)) { throw 'Daily UI deployment is incomplete' }
$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop 'GFN HUD Guard.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
if ((Test-Path $linkPath) -and ($link.TargetPath -ne $python -or $link.Arguments -ne ('"' + $script + '"'))) {
    throw 'An unrelated desktop shortcut already uses this name; preserved'
}
$link.TargetPath = $python
$link.Arguments = '"' + $script + '"'
$link.WorkingDirectory = $root
$link.Description = 'GFN HUD Guard: daily NR and optical-flow controls'
$link.IconLocation = 'C:\Windows\System32\shell32.dll,17'
$link.Save()

# An on-demand interactive launcher is used for remote validation, never autostart.
$taskName = 'GFN-HUD-Guard-Panel'
$old = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($old -and ($old.State -eq 'Running' -or $old.Actions.Arguments -ne ('"' + $script + '"'))) {
    throw 'Existing panel task is active or unrelated; preserved'
}
$principal = (Get-ScheduledTask 'GFN-Codex-Live-Run-20260921').Principal
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $script + '"') -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Write-Output ('Desktop shortcut ready: ' + $linkPath)
Write-Output 'On-demand interactive panel launcher ready. No startup trigger is installed.'
