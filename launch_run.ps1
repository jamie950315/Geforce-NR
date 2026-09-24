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
$neutral = New-ScheduledTaskAction -Execute $python -Argument '-c "pass"' -WorkingDirectory $root
$entryArgument = '"' + $entry + '"'
$stored = $task.Actions[0].Arguments
if ($task.Triggers -or $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $python -or
    $task.Actions[0].WorkingDirectory -ne $root -or
    !($stored -eq $neutral.Arguments -or $stored -eq $entryArgument -or
      $stored.StartsWith($entryArgument + ' '))) {
    throw 'The interactive launcher has an unexpected action or trigger; it has been preserved'
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $entry + '" ' + $RunArgs) -WorkingDirectory $root
try {
    Set-ScheduledTask -TaskName $name -Action $action | Out-Null
    Start-ScheduledTask -TaskName $name
    Start-Sleep -Milliseconds 750
} finally {
    Set-ScheduledTask -TaskName $name -Action $neutral | Out-Null
}
Write-Output 'DISPATCHED; inspect the run outcome before claiming completion.'
