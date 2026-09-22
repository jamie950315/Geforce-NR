$ErrorActionPreference = 'Stop'
Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Format-Table InterfaceAlias,NextHop,RouteMetric
Get-NetRoute -AddressFamily IPv4 | Where-Object DestinationPrefix -In @('0.0.0.0/1','128.0.0.0/1') | Format-Table InterfaceAlias,NextHop,DestinationPrefix,RouteMetric
Get-NetAdapter | Format-Table Name,InterfaceDescription,Status
Get-Process | Where-Object ProcessName -Match 'clash|sing|warp|tailscale|vpn|v2ray|nekoray' | Format-Table Id,ProcessName
$gfnIds = (Get-Process GeForceNOW -ErrorAction SilentlyContinue).Id
Get-NetTCPConnection -State Established | Where-Object OwningProcess -In $gfnIds | Format-Table OwningProcess,RemoteAddress,RemotePort
Find-NetRoute -RemoteIPAddress '66.22.144.48' | Format-List InterfaceAlias,InterfaceIndex,NextHop,DestinationPrefix,RouteMetric
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
if (Test-Path $ts) {
    $prefs = & $ts debug prefs | ConvertFrom-Json
    $prefs | Select-Object ExitNodeID,ExitNodeIP,RouteAll | Format-List
}
