[CmdletBinding()]
param(
    [ValidateSet('calibrate', 'cancel-calibration', 'join', 'invite', 'accept', 'status')]
    [string]$Action = 'status',
    [ValidateSet('auto', 'ai', 'observer')][string]$Target = 'auto',
    [int]$Port = 18001
)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid local API port' }
$base = "http://127.0.0.1:$Port/api/v1/vrchat"
if ($Action -in @('invite', 'accept') -and $Target -eq 'auto') {
    throw 'Invite/accept require an explicit -Target ai or -Target observer.'
}
if ($Action -eq 'status') {
    $state = Invoke-RestMethod -Uri $base -TimeoutSec 10
    [pscustomobject]@{ calibration = $state.calibration; rooms = $state.rooms } | ConvertTo-Json -Depth 6
    return
}
if ($Action -in @('calibrate', 'cancel-calibration')) {
    $command = if ($Action -eq 'calibrate') { 'start' } else { 'cancel' }
    $result = Invoke-RestMethod -Method Post -Uri "$base/calibration" -ContentType 'application/json' `
        -Body (@{ action = $command } | ConvertTo-Json) -TimeoutSec 10
    $deadline = (Get-Date).AddSeconds(75)
    while ($Action -eq 'calibrate' -and $result.active) {
        if ((Get-Date) -ge $deadline) {
            Invoke-RestMethod -Method Post -Uri "$base/calibration" -ContentType 'application/json' `
                -Body '{"action":"cancel"}' -TimeoutSec 10 | Out-Null
            throw 'Calibration timed out and was cancelled; no success claimed.'
        }
        Start-Sleep -Milliseconds 500
        $result = (Invoke-RestMethod -Uri $base -TimeoutSec 10).calibration
    }
    $result | ConvertTo-Json -Depth 6
    if ($Action -eq 'calibrate' -and $result.stage -ne 'completed') { throw $result.error }
    return
}
$result = Invoke-RestMethod -Method Post -Uri "$base/rooms" -ContentType 'application/json' `
    -Body (@{ action = $Action; target = $Target } | ConvertTo-Json) -TimeoutSec 125
$result | ConvertTo-Json -Depth 6
if ($Action -in @('join', 'accept') -and -not $result.same_instance) {
    throw 'The two clients have not confirmed arrival in the same instance.'
}
