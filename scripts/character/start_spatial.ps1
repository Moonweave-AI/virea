[CmdletBinding()]
param([Parameter(Mandatory)][string]$DataRoot)
$ErrorActionPreference = 'Stop'
if (Get-NetTCPConnection -LocalPort 8085 -State Listen -ErrorAction SilentlyContinue) {
    $health = Invoke-RestMethod http://127.0.0.1:8085/health
    if ($health.model -ne 'ARDY-Core-RP-20FPS-Horizon8') { throw 'Unexpected service on port 8085' }
    return
}
$python = Join-Path $DataRoot 'runtimes/ardy/Scripts/python.exe'
$logs = Join-Path $DataRoot 'logs/spatial'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$previousPath = $env:PYTHONPATH
$previousBytecode = $env:PYTHONDONTWRITEBYTECODE
$arguments = @('-B', '-m', 'spatial.server', '--model-dir', (Join-Path $DataRoot 'models/ardy-core-20fps-h8'),
    '--text-dir', (Join-Path $DataRoot 'models/ardy-text-nf4')) | ForEach-Object { '"' + $_ + '"' }
try {
    $env:PYTHONPATH = $PSScriptRoot
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log')
} finally {
    $env:PYTHONPATH = $previousPath
    $env:PYTHONDONTWRITEBYTECODE = $previousBytecode
}
@{ pid = $process.Id; started = $process.StartTime.ToUniversalTime().ToString('o'); executable = $python } |
    ConvertTo-Json | Set-Content (Join-Path $logs 'process.json') -Encoding utf8
Write-Output "Spatial worker starting at http://127.0.0.1:8085; logs: $logs"
