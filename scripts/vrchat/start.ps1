[CmdletBinding()]
param(
    [string]$Settings = (Join-Path $PSScriptRoot '../../.virea-runtime/vrchat/config/stack.json'),
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$settingsPath = (Resolve-Path -LiteralPath $Settings).Path
$stack = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$logs = Join-Path $repo '.virea-runtime/vrchat/logs/stack'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$ownedFile = Join-Path $logs 'owned-processes.json'
$owned = @()
if (Test-Path -LiteralPath $ownedFile) { $owned = @(Get-Content -LiteralPath $ownedFile -Raw | ConvertFrom-Json) }

function Read-Health($Service) {
    try {
        $value = Invoke-RestMethod -Uri $Service.health -TimeoutSec 3
        foreach ($field in $Service.expect.PSObject.Properties) {
            if ($value.($field.Name) -ne $field.Value) { return $false }
        }
        return $true
    } catch { return $false }
}

$report = @()
foreach ($service in $stack.services) {
    if ($service.name -notmatch '^[a-z0-9-]+$') { throw 'Invalid service name' }
    $endpoint = [Uri]$service.health
    if ($endpoint.Host -ne '127.0.0.1' -or $endpoint.Scheme -ne 'http') { throw 'Health endpoints must be local HTTP' }
    if (Read-Health $service) {
        $report += @{ name = $service.name; status = 'ready'; reused = $true }
        Write-Output "$($service.name): ready (existing service)"
        continue
    }
    if ($CheckOnly) { $report += @{ name = $service.name; status = 'unavailable' }; continue }
    if (Get-NetTCPConnection -LocalPort $endpoint.Port -State Listen -ErrorAction SilentlyContinue) {
        throw "$($service.name): port $($endpoint.Port) is occupied by a service that failed its identity/readiness check. See $logs"
    }
    if (!(Test-Path -LiteralPath $service.executable -PathType Leaf)) { throw "Missing executable for $($service.name): $($service.executable)" }
    $previous = @{}
    try {
        foreach ($entry in $service.environment.PSObject.Properties) {
            $previous[$entry.Name] = [Environment]::GetEnvironmentVariable($entry.Name, 'Process')
            [Environment]::SetEnvironmentVariable($entry.Name, [string]$entry.Value, 'Process')
        }
        # Pass data arguments directly to the executable, never evaluate a command string.
        $quoted = @($service.arguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' })
        $process = Start-Process -FilePath $service.executable -ArgumentList $quoted -WorkingDirectory $repo -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logs "$($service.name).out.log") -RedirectStandardError (Join-Path $logs "$($service.name).err.log") -PassThru
    } finally {
        foreach ($entry in $previous.GetEnumerator()) { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process') }
    }
    $owned += @{ name = $service.name; pid = $process.Id; started = $process.StartTime.ToUniversalTime().ToString('o'); executable = $service.executable }
    ConvertTo-Json -InputObject @($owned) -Depth 4 | Set-Content -LiteralPath $ownedFile -Encoding utf8
    Write-Output "$($service.name): starting; logs in $logs"
    $deadline = (Get-Date).AddSeconds(1200)
    while (!(Read-Health $service)) {
        if ($process.HasExited) { throw "$($service.name) exited ($($process.ExitCode)); inspect $logs" }
        if ((Get-Date) -ge $deadline) { throw "$($service.name) readiness timed out; inspect $logs" }
        Start-Sleep -Seconds 2
    }
    $report += @{ name = $service.name; status = 'ready'; reused = $false }
    Write-Output "$($service.name): ready"
}
ConvertTo-Json -InputObject @($report) -Depth 4 | Set-Content -LiteralPath (Join-Path $logs 'health.json') -Encoding utf8
if (@($report | Where-Object status -ne 'ready').Count) { throw "Some services are unavailable; see $logs/health.json" }
Write-Output "VIREA: $($stack.ui). AI client and observer remain separate; launch with start_ai_client.ps1."
