param([Parameter(Mandatory=$true)][string]$RunArgs)
$ErrorActionPreference = 'Stop'
$name = 'GFN-Codex-Live-Run-20260921'
$task = Get-ScheduledTask $name -ErrorAction Stop
if ($task.State -eq 'Running') { throw 'Existing run preserved' }
$root = $PSScriptRoot
$python = Join-Path (Split-Path $root -Parent) 'gfn-nr-core\.venv\Scripts\pythonw.exe'
$entry = Join-Path $root 'live_run.py'
if (!(Test-Path -LiteralPath $python -PathType Leaf) -or !(Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw 'The isolated launcher or Core Python runtime is missing'
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '" ' + $RunArgs) -WorkingDirectory $root
Set-ScheduledTask -TaskName $name -Action $action | Out-Null
Start-ScheduledTask -TaskName $name
Write-Output 'DISPATCHED; inspect the run outcome before claiming completion.'
