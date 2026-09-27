param([Parameter(Mandatory=$true)][string]$Python,
      [string]$PrincipalTask = 'GFN-Codex-Live-Run-20260921')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'task_control.ps1')
$id = [guid]::NewGuid().ToString('N')
$name = 'GFN-NR-Review-' + $id
$root = (New-Item -ItemType Directory -Path (Join-Path $env:TEMP $name)).FullName
$entry = Join-Path $root 'fixture.py'
$resultFile = Join-Path $root 'result.json'
$fixture = @'
import argparse, json, os, time
from pathlib import Path
ap = argparse.ArgumentParser()
ap.add_argument('--request-id')
ap.add_argument('--delay', type=float, default=0)
ap.add_argument('--stale', action='store_true')
ap.add_argument('--fail', action='store_true')
a = ap.parse_args()
time.sleep(a.delay)
if a.fail:
    raise SystemExit(3)
if not a.stale:
    Path(__file__).with_name('result.json').write_text(json.dumps({'request_id': a.request_id, 'ok': True}))
'@
$fixture | Set-Content -LiteralPath $entry -Encoding UTF8
$neutral = '"' + $entry + '"'
$action = New-ScheduledTaskAction -Execute $Python -Argument $neutral -WorkingDirectory $root
$principal = (Get-ScheduledTask -TaskName $PrincipalTask).Principal
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$created = $false
$parameters = @{Name=$name; Python=$Python; Entry=$entry; Root=$root; NeutralArguments=$neutral; ResultFile=$resultFile}
function Assert-Neutral {
    $current = Get-ScheduledTask -TaskName $name
    if ($current.Actions[0].Arguments -ne $neutral -or $current.Triggers) { throw 'Task action was not restored' }
}
function Expect-Failure([scriptblock]$Operation, [string]$Pattern) {
    try { & $Operation } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        return
    }
    throw ('Expected failure matching ' + $Pattern)
}
try {
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
    $created = $true
    $result = Invoke-GfnTask @parameters -Arguments '--delay 0.2'
    if (!$result.ok -or !$result.request_id) { throw 'Missing current probe result' }
    Assert-Neutral
    Expect-Failure { Invoke-GfnTask @parameters -Arguments '--stale' } 'stale'
    Assert-Neutral
    Expect-Failure { Invoke-GfnTask @parameters -Arguments '--fail' } 'Task failed'
    Assert-Neutral
    Expect-Failure { Invoke-GfnTask @parameters -Arguments '--delay 5' -TimeoutSeconds 1 } 'in time'
    Assert-Neutral
    $limit = [Diagnostics.Stopwatch]::StartNew()
    while ((Get-ScheduledTask -TaskName $name).State -in @('Running','Queued')) {
        if ($limit.Elapsed.TotalSeconds -gt 5) { throw 'Timed-out instance did not stop' }
        Start-Sleep -Milliseconds 100
    }
    $asyncParameters = $parameters.Clone()
    $asyncParameters.Remove('ResultFile')
    Invoke-GfnTask @asyncParameters -Arguments '--delay 2'
    Assert-Neutral
    $limit.Restart()
    while ((Get-ScheduledTask -TaskName $name).State -in @('Running','Queued')) {
        if ($limit.Elapsed.TotalSeconds -gt 10) { throw 'Async instance did not finish' }
        Start-Sleep -Milliseconds 100
    }
    if ((Get-ScheduledTaskInfo -TaskName $name).LastTaskResult -ne 0) { throw 'Async run was interrupted' }
    $lockJob = Start-Job -ArgumentList $name -ScriptBlock {
        param($TaskName)
        $mutex = New-Object System.Threading.Mutex($false, ('Global\GFN-NR-Task-' + $TaskName))
        try {
            $null = $mutex.WaitOne()
            Write-Output 'acquired'
            Start-Sleep -Seconds 15
        } finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
    }
    try {
        $limit.Restart()
        while (!(Receive-Job $lockJob -Keep)) {
            if ($limit.Elapsed.TotalSeconds -gt 10) { throw 'Lock test setup timed out' }
            Start-Sleep -Milliseconds 100
        }
        Expect-Failure { Invoke-GfnTask @parameters } 'Another caller owns'
        Assert-Neutral
    } finally { Stop-Job $lockJob; Remove-Job $lockJob }
    # Mock only the read preflight; the actual task must remain untouched.
    function Get-ScheduledTask { param($TaskName, $ErrorAction) return [pscustomobject]@{State='Queued'} }
    try { Expect-Failure { Invoke-GfnTask @parameters } 'queued task is preserved' }
    finally { Remove-Item Function:\Get-ScheduledTask }
    Assert-Neutral
    Write-Output 'PASS: fresh result, stale rejection, failure cleanup, timeout, async dispatch, concurrent and queued preservation'
} finally {
    if ($created) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task.State -in @('Running','Queued')) { Stop-ScheduledTask -TaskName $name }
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
    Remove-Item -LiteralPath $root -Recurse -Force
}
