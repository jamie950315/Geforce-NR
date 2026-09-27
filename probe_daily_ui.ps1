param([string]$ProbeArgs = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'task_control.ps1')
$entry = Join-Path $PSScriptRoot 'daily_ui_probe.py'
$parameters = @{
    Name = 'Geforce-NR-UI-Probe'
    Python = (Join-Path (Split-Path $PSScriptRoot -Parent) 'gfn-nr-overlay\.venv\Scripts\pythonw.exe')
    Entry = $entry; Root = $PSScriptRoot; Arguments = $ProbeArgs
    NeutralArguments = ('"' + $entry + '"')
    ResultFile = (Join-Path $PSScriptRoot 'daily-probe.json')
    CreateFromTask = 'GFN-Codex-Live-Run-20260921'
}
Invoke-GfnTask @parameters | ConvertTo-Json -Depth 8
