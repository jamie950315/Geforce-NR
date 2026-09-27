# Serialize action changes across console/SSH sessions and track the dispatched instance.
function Invoke-GfnTask {
    param(
        [string]$Name, [string]$Python, [string]$Entry, [string]$Root,
        [string]$Arguments, [string]$NeutralArguments,
        [string]$ResultFile, [string]$CreateFromTask, [switch]$AllowLegacyRun,
        [int]$TimeoutSeconds = 20
    )
    $mutex = New-Object System.Threading.Mutex($false, ('Global\GFN-NR-Task-' + $Name))
    $locked = $false
    $changed = $false
    $instance = $null
    $dispatched = $false
    try {
        try { $locked = $mutex.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { $locked = $true }
        if (!$locked) { throw 'Another caller owns this task action; preserved' }
        if (!(Test-Path -LiteralPath $Python -PathType Leaf) -or
            !(Test-Path -LiteralPath $Entry -PathType Leaf)) {
            throw 'The isolated script or Python runtime is missing'
        }
        $neutral = New-ScheduledTaskAction -Execute $Python -Argument $NeutralArguments -WorkingDirectory $Root
        $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        if (!$task) {
            if (!$CreateFromTask) { throw 'The on-demand task is missing' }
            $parentTask = Get-ScheduledTask -TaskName $CreateFromTask -ErrorAction Stop
            $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
            Register-ScheduledTask -TaskName $Name -Action $neutral -Principal $parentTask.Principal -Settings $settings | Out-Null
            $task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
        }
        if ($task.State -in @('Running', 'Queued')) { throw 'Existing running or queued task is preserved' }
        $stored = if ($task.Actions.Count -eq 1) { $task.Actions[0].Arguments } else { $null }
        $entryArgument = '"' + $Entry + '"'
        $owned = $stored -eq $NeutralArguments
        if ($AllowLegacyRun -and $stored) {
            $owned = $owned -or $stored -eq $entryArgument -or $stored.StartsWith($entryArgument + ' ')
        }
        if ($task.Triggers -or $task.Actions.Count -ne 1 -or !$owned -or
            $task.Actions[0].Execute -ne $Python -or $task.Actions[0].WorkingDirectory -ne $Root) {
            throw 'The task has an unexpected action, directory, or trigger; preserved'
        }
        $requestId = [guid]::NewGuid().ToString('N')
        $taskArguments = ($entryArgument + ' ' + $Arguments).TrimEnd()
        if ($ResultFile) { $taskArguments += ' --request-id ' + $requestId }
        $action = New-ScheduledTaskAction -Execute $Python -Argument $taskArguments -WorkingDirectory $Root
        Set-ScheduledTask -TaskName $Name -Action $action | Out-Null
        $changed = $true
        $scheduler = New-Object -ComObject Schedule.Service
        $scheduler.Connect()
        $registered = $scheduler.GetFolder('\').GetTask($Name)
        $instance = $registered.Run($null)
        $instanceId = $instance.InstanceGuid
        $timer = [Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            $current = $null
            $instances = $registered.GetInstances(0)
            for ($index = 1; $index -le $instances.Count; $index++) {
                $candidate = $instances.Item($index)
                if ($candidate.InstanceGuid -eq $instanceId) { $current = $candidate; break }
            }
            if (!$current) {
                if ($registered.LastTaskResult -ne 0) { throw ('Task failed: ' + $registered.LastTaskResult) }
                break
            }
            # A queued instance must retain its requested action until it starts.
            if (!$ResultFile -and $current.State -eq 4 -and $current.CurrentAction) { break }
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) { throw 'Task did not complete the requested dispatch in time' }
            Start-Sleep -Milliseconds 100
        }
        if ($ResultFile) {
            $result = Get-Content -LiteralPath $ResultFile -Raw | ConvertFrom-Json
            if ($result.request_id -ne $requestId) { throw 'Probe result is stale or belongs to another request' }
            $result
        }
        $dispatched = $true
    } finally {
        try {
            # Stop only this call's instance, never an unrelated task instance.
            if ($instance -and !$dispatched) {
                $instances = $registered.GetInstances(0)
                for ($index = 1; $index -le $instances.Count; $index++) {
                    $current = $instances.Item($index)
                    if ($current.InstanceGuid -eq $instanceId) { $current.Stop() }
                }
            }
        } finally {
            try {
                if ($changed) { Set-ScheduledTask -TaskName $Name -Action $neutral | Out-Null }
            } finally {
                if ($locked) { $mutex.ReleaseMutex() }
                $mutex.Dispose()
            }
        }
    }
}
