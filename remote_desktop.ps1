param([string]$ProbeArgs = '')
$ErrorActionPreference = 'Stop'
$name = 'GFN-Codex-Live-Probe-20260921'
$root = $PSScriptRoot
$python = Join-Path (Split-Path $root -Parent) 'gfn-nr-overlay\.venv\Scripts\pythonw.exe'
$entry = Join-Path $root 'desktop_probe.py'
if (!(Test-Path -LiteralPath $python -PathType Leaf) -or !(Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw 'The desktop probe or overlay Python runtime is missing'
}
$existing = Get-ScheduledTask $name -ErrorAction Stop
if ($existing.State -eq 'Running') { throw 'Existing desktop probe is preserved' }
$neutral = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '"') -WorkingDirectory $root
if ($existing.Actions.Count -ne 1 -or $existing.Actions[0].Execute -ne $python -or
    $existing.Actions[0].Arguments -ne $neutral.Arguments) {
    throw 'The desktop probe has an unexpected action; it has been preserved'
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '" ' + $ProbeArgs) -WorkingDirectory $root
try {
    Set-ScheduledTask -TaskName $name -Action $action | Out-Null
    Start-ScheduledTask -TaskName $name
    Start-Sleep -Seconds 4
    for ($attempt = 0; $attempt -lt 20 -and (Get-ScheduledTask $name).State -eq 'Running'; $attempt++) {
        Start-Sleep -Milliseconds 500
    }
    if ((Get-ScheduledTask $name).State -eq 'Running') { throw 'Desktop probe did not finish' }
    $info = Get-ScheduledTaskInfo $name
    if ($info.LastTaskResult -ne 0) { throw "Desktop probe failed: $($info.LastTaskResult)" }
    $result = Get-Content (Join-Path $root 'desktop.json') -Raw | ConvertFrom-Json
    $windows = @($result.windows | Where-Object { $_.title -match 'GeForce NOW|Geforce NR' } |
        Select-Object hwnd, title, rect, pid)
    $foregroundTitle = if ($result.foreground_title -match 'GeForce NOW|Geforce NR') {
        $result.foreground_title
    } else { $null }
    [pscustomobject]@{
        foreground_title = $foregroundTitle
        foreground_is_gfn = [bool]($result.foreground_title -match 'GeForce NOW')
        screenshot_captured = [bool]$result.screenshot_captured
        screenshot_size = $result.screenshot_size
        windows = $windows
    } | ConvertTo-Json -Depth 4
} finally {
    if ((Get-ScheduledTask $name).State -eq 'Running') {
        Stop-ScheduledTask $name
    }
    Set-ScheduledTask -TaskName $name -Action $neutral | Out-Null
}
