# Read-only route and adapter metadata. Output can contain private network identities.
$ErrorActionPreference = 'Stop'
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
if (Test-Path $ts) {
    $state = & $ts status --json | ConvertFrom-Json
    $prefs = & $ts debug prefs | ConvertFrom-Json
    [pscustomobject]@{ExitNodeID=$prefs.ExitNodeID; ExitNodeIP=$prefs.ExitNodeIP; BackendState=$state.BackendState} | ConvertTo-Json -Compress
    foreach ($entry in $state.Peer.PSObject.Properties) {
        $peer = $entry.Value
        if ($peer.ExitNode -or $peer.ID -eq $prefs.ExitNodeID) {
            $peer | Select-Object HostName,Online,Active,ExitNode,CurAddr,Relay,RxBytes,TxBytes | ConvertTo-Json -Compress
        }
    }
}
Get-NetAdapterStatistics | Select-Object Name,ReceivedPacketErrors,OutboundPacketErrors,ReceivedDiscardedPackets,OutboundDiscardedPackets | ConvertTo-Json -Compress
Get-Process GeForceNOW -ErrorAction Stop | Select-Object Id,SessionId,CPU,WorkingSet64 | ConvertTo-Json -Compress
