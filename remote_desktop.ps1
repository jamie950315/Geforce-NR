param([string]$ProbeArgs = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'task_control.ps1')
$entry = Join-Path $PSScriptRoot 'desktop_probe.py'
$parameters = @{
    Name = 'GFN-Codex-Live-Probe-20260921'
    Python = (Join-Path (Split-Path $PSScriptRoot -Parent) 'gfn-nr-overlay\.venv\Scripts\pythonw.exe')
    Entry = $entry; Root = $PSScriptRoot; Arguments = $ProbeArgs
    NeutralArguments = ('"' + $entry + '"')
    ResultFile = (Join-Path $PSScriptRoot 'desktop.json')
}
$result = Invoke-GfnTask @parameters
$windows = @($result.windows | Where-Object { $_.title -match 'GeForce NOW|Geforce NR' } |
    Select-Object hwnd, title, rect, pid)
$foregroundTitle = if ($result.foreground_title -match 'GeForce NOW|Geforce NR') {
    $result.foreground_title
} else { $null }
[pscustomobject]@{
    foreground_title = $foregroundTitle
    foreground_is_gfn = [bool]$result.foreground_is_gfn
    screenshot_captured = [bool]$result.screenshot_captured
    screenshot_size = $result.screenshot_size
    screenshot_bounds = $result.screenshot_bounds
    focus_error = $result.focus_error
    capture_error = $result.capture_error
    windows = $windows
} | ConvertTo-Json -Depth 4
