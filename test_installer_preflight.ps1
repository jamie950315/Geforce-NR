$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path (Split-Path $root -Parent) 'gfn-nr-core\.venv\Scripts\pythonw.exe'
$entry = Join-Path $root 'daily_ui.py'
$global:gfnReviewComCalls = 0
function Test-Path { param($LiteralPath, $PathType) return $true }
function New-Object { param($ComObject) $global:gfnReviewComCalls++; throw 'Shortcut mutation reached' }
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    if ($TaskName -eq 'GFN-Codex-Live-Run-20260921') { return [pscustomobject]@{Principal=@{}} }
    if ($TaskName -eq 'Geforce-NR-Panel') { return $global:gfnReviewExistingTask }
    return $null
}
foreach ($fault in @('executable', 'queued', 'triggers', 'directory', 'multiple-actions')) {
    $action = [pscustomobject]@{Execute=$python; Arguments=('"' + $entry + '"'); WorkingDirectory=$root}
    $global:gfnReviewExistingTask = [pscustomobject]@{State='Ready'; Triggers=$null; Actions=@($action)}
    switch ($fault) {
        'executable' { $action.Execute = 'unrelated.exe' }
        'queued' { $global:gfnReviewExistingTask.State = 'Queued' }
        'triggers' { $global:gfnReviewExistingTask.Triggers = @('existing-trigger') }
        'directory' { $action.WorkingDirectory = 'C:\unrelated' }
        'multiple-actions' { $global:gfnReviewExistingTask.Actions = @($action, $action) }
    }
    $failed = $false
    try { & (Join-Path $root 'install_daily_ui.ps1') }
    catch {
        if ($_.Exception.Message -notmatch 'preserved before installation') { throw }
        $failed = $true
    }
    if (!$failed) { throw ('Installer accepted unrelated task: ' + $fault) }
}
if ($global:gfnReviewComCalls -ne 0) { throw 'Installer touched shortcuts before task preflight' }
Write-Output 'PASS: installer refuses unrelated/queued tasks before shortcut mutation'
