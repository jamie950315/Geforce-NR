param([Parameter(Mandatory=$true)][string]$RunArgs)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'task_control.ps1')
$python = Join-Path (Split-Path $PSScriptRoot -Parent) 'gfn-nr-core\.venv\Scripts\pythonw.exe'
$parameters = @{
    Name = 'GFN-Codex-Live-Run-20260921'; Python = $python
    Entry = (Join-Path $PSScriptRoot 'live_run.py'); Root = $PSScriptRoot
    Arguments = $RunArgs; NeutralArguments = '-c "pass"'; AllowLegacyRun = $true
}
Invoke-GfnTask @parameters
Write-Output 'DISPATCHED; inspect the run outcome before claiming completion.'
