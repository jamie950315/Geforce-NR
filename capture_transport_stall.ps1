# Bounded, explicit packet-prefix/PresentMon diagnostics; generated evidence stays local.
param(
    [Parameter(Mandatory=$true)][string]$ExitAddress,
    [Parameter(Mandatory=$true)][int]$ExitPort,
    [Parameter(Mandatory=$true)][string]$Name
)
$ErrorActionPreference = 'Stop'
if ($Name -notmatch '^[a-z0-9-]+$') { throw 'Invalid isolated run name' }
[void][Net.IPAddress]::Parse($ExitAddress)
if ($ExitPort -lt 1 -or $ExitPort -gt 65535) { throw 'Invalid peer UDP port' }
$root = $PSScriptRoot
$run = Join-Path $root ('runs\' + $Name)
if (Test-Path $run) { throw 'Existing evidence is preserved' }
$pkt = 'C:\Windows\System32\pktmon.exe'
& C:\Windows\System32\logman.exe query PktMon -ets 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { throw 'Existing packet monitor session is preserved' }
$existingFilters = & $pkt filter list
if ($LASTEXITCODE -ne 0 -or ($existingFilters -match '^\s*\d+\s+')) {
    throw 'Existing packet filters are preserved; isolated capture requires no filters'
}
New-Item -ItemType Directory -Path $run | Out-Null
$filter = 'GFN-NR-Stall'
$started = $false
$filterAdded = $false
try {
    & $pkt filter add $filter -t UDP -i $ExitAddress -p $ExitPort
    if ($LASTEXITCODE -ne 0) { throw 'Packet filter creation failed' }
    $filterAdded = $true
    & $pkt start --capture --comp nics --pkt-size 64 --file-size 128 --file-name (Join-Path $run 'headers.etl')
    if ($LASTEXITCODE -ne 0) { throw 'Packet capture did not start; no existing session is stopped' }
    $started = $true
    $qpc = [Diagnostics.Stopwatch]::GetTimestamp()
    $utc = [DateTimeOffset]::UtcNow
    [pscustomobject]@{
        qpc=$qpc; qpc_frequency=[Diagnostics.Stopwatch]::Frequency
        unix_milliseconds=$utc.ToUnixTimeMilliseconds(); utc=$utc.ToString('o')
        packet_limit_bytes=64; peer=$ExitAddress; port=$ExitPort
    } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $run 'clock.json')
    & (Join-Path $root 'PresentMon-2.5.1-x64.exe') --process_name GeForceNOW.exe --session_name $Name --output_file (Join-Path $run 'presents.csv') --qpc_time_ms --v1_metrics --no_track_input --no_console_stats --timed 90 --terminate_after_timed
    if ($LASTEXITCODE -ne 0) { throw 'PresentMon capture failed' }
} finally {
    if ($started) { & $pkt stop }
    if ($filterAdded) { & $pkt filter remove $filter }
}
& $pkt etl2txt (Join-Path $run 'headers.etl') --out (Join-Path $run 'headers.txt') --timestamp --brief
if ($LASTEXITCODE -ne 0) { throw 'Header timestamp conversion failed' }
