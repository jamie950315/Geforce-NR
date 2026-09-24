param([string]$ProbeArgs = '')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$name = 'Geforce-NR-UI-Probe'
$python = Join-Path (Split-Path $root -Parent) 'gfn-nr-overlay\.venv\Scripts\pythonw.exe'
$script = Join-Path $root 'daily_ui_probe.py'
if (!(Test-Path -LiteralPath $python -PathType Leaf) -or !(Test-Path -LiteralPath $script -PathType Leaf)) {
    throw 'The UI probe or overlay Python runtime is missing'
}
$neutral = New-ScheduledTaskAction -Execute $python -Argument ('"' + $script + '"') -WorkingDirectory $root
$old = Get-ScheduledTask $name -ErrorAction SilentlyContinue
if ($old) {
    if ($old.State -eq 'Running') { throw 'Existing UI probe is preserved' }
    if ($old.Triggers -or $old.Actions.Count -ne 1 -or $old.Actions[0].Execute -ne $python -or
        $old.Actions[0].Arguments -ne $neutral.Arguments -or
        $old.Actions[0].WorkingDirectory -ne $root) {
        throw 'The UI probe has an unexpected action or trigger; it has been preserved'
    }
} else {
    $principal = (Get-ScheduledTask 'GFN-Codex-Live-Run-20260921').Principal
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $name -Action $neutral -Principal $principal -Settings $settings | Out-Null
}
$action = New-ScheduledTaskAction -Execute $python -Argument (('"' + $script + '" ' + $ProbeArgs).TrimEnd()) -WorkingDirectory $root
try {
    Set-ScheduledTask -TaskName $name -Action $action | Out-Null
    Start-ScheduledTask $name
    Start-Sleep -Seconds 2
    for ($attempt = 0; $attempt -lt 10 -and (Get-ScheduledTask $name).State -eq 'Running'; $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if ((Get-ScheduledTask $name).State -eq 'Running') { throw 'UI probe did not finish' }
    if ((Get-ScheduledTaskInfo $name).LastTaskResult -ne 0) { throw 'UI probe failed' }
    Get-Content (Join-Path $root 'daily-probe.json')
} finally {
    if ((Get-ScheduledTask $name).State -eq 'Running') { Stop-ScheduledTask $name }
    Set-ScheduledTask -TaskName $name -Action $neutral | Out-Null
}
