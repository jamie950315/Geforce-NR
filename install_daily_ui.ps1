param([switch]$Check)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$parent = Split-Path $root -Parent
$python = Join-Path $parent 'gfn-nr-core\.venv\Scripts\pythonw.exe'
$script = Join-Path $root 'daily_ui.py'
$requirements = [ordered]@{
    'Daily UI' = $script
    'Daily backend' = (Join-Path $root 'daily_backend.py')
    'Daily launcher' = (Join-Path $root 'live_run.py')
    'Mask editor' = (Join-Path $root 'mask_editor.py')
    'Mask profiles' = (Join-Path $root 'mask_profiles.py')
    'Window preview' = (Join-Path $root 'window_preview.py')
    'Core Python runtime' = $python
    'Lab Windows adapter' = (Join-Path $parent 'gfn-nvofa-lab-20260920\gfn_core\windows.py')
    'Lab controller' = (Join-Path $parent 'gfn-nvofa-lab-20260920\gfn_core\engine.py')
    'Lab appearance' = (Join-Path $parent 'gfn-nvofa-lab-20260920\appearance.json')
    'HUD launcher dependency' = (Join-Path $parent 'gfn-hud-live-20260921-7b03\live_hud.py')
    'Repaired native worker' = (Join-Path $root 'native-repaired\nvngx.dll')
    'NR runtime' = (Join-Path $root 'native-repaired\nvngx_dlssnr.dll')
    'Repaired build record' = (Join-Path $root 'repaired-build.json')
}
$missing = @($requirements.GetEnumerator() | Where-Object { !(Test-Path -LiteralPath $_.Value -PathType Leaf) })
if ($missing.Count) {
    foreach ($item in $missing) { Write-Output ('Missing ' + $item.Key + ': ' + $item.Value) }
    throw 'Daily UI layout is incomplete; no desktop shortcut or scheduled task was changed'
}
$launcherTask = Get-ScheduledTask 'GFN-Codex-Live-Run-20260921' -ErrorAction SilentlyContinue
if (!$launcherTask) { throw 'The on-demand interactive launcher task is missing; no desktop shortcut or scheduled task was changed' }
if ($Check) {
    Write-Output 'Daily UI layout and on-demand launcher task are present. No changes were made.'
    return
}
$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop 'Geforce NR.lnk'
$shell = New-Object -ComObject WScript.Shell
$legacyPath = Join-Path $desktop 'GFN HUD Guard.lnk'
if (Test-Path $legacyPath) {
    $legacyLink = $shell.CreateShortcut($legacyPath)
    if ($legacyLink.TargetPath -ne $python -or $legacyLink.Arguments -ne ('"' + $script + '"')) {
        throw 'An unrelated legacy shortcut is preserved'
    }
    if (Test-Path $linkPath) { throw 'Both shortcut names exist; preserved for review' }
    Move-Item -LiteralPath $legacyPath -Destination $linkPath
}
$link = $shell.CreateShortcut($linkPath)
if ((Test-Path $linkPath) -and ($link.TargetPath -ne $python -or $link.Arguments -ne ('"' + $script + '"'))) {
    throw 'An unrelated desktop shortcut already uses this name; preserved'
}
$link.TargetPath = $python
$link.Arguments = '"' + $script + '"'
$link.WorkingDirectory = $root
$link.Description = 'Geforce NR: daily NR and optical-flow controls'
$link.IconLocation = 'C:\Windows\System32\shell32.dll,17'
$link.Save()

# An on-demand interactive launcher is used for remote validation, never autostart.
$taskName = 'Geforce-NR-Panel'
$old = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($old -and ($old.State -eq 'Running' -or $old.Actions.Arguments -ne ('"' + $script + '"'))) {
    throw 'Existing panel task is active or unrelated; preserved'
}
$principal = $launcherTask.Principal
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $script + '"') -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null

# Migrate only this deployment's inactive, on-demand legacy task registrations.
foreach ($entry in @(
    @{Name='GFN-HUD-Guard-Panel'; Script=$script},
    @{Name='GFN-HUD-Guard-UI-Probe'; Script=(Join-Path $root 'daily_ui_probe.py')}
)) {
    $legacy = Get-ScheduledTask -TaskName $entry.Name -ErrorAction SilentlyContinue
    if (!$legacy) { continue }
    if ($legacy.State -eq 'Running' -or $legacy.Triggers -or
        !$legacy.Actions.Arguments.StartsWith('"' + $entry.Script + '"')) {
        throw ('Legacy task is active or unrelated; preserved: ' + $entry.Name)
    }
    $backupDir = Join-Path $root 'evidence\task-name-migration'
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $backup = Join-Path $backupDir ($entry.Name + '.xml')
    if (!(Test-Path $backup)) {
        Export-ScheduledTask -TaskName $entry.Name | Set-Content -Encoding Unicode -LiteralPath $backup
    }
    Unregister-ScheduledTask -TaskName $entry.Name -Confirm:$false
}
Write-Output ('Desktop shortcut ready: ' + $linkPath)
Write-Output 'On-demand interactive panel launcher ready. No startup trigger is installed.'
