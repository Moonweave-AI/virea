[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$Settings,
    [int]$Port = 0
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtimePython = (Resolve-Path -LiteralPath $Python).Path
$settingsPath = (Resolve-Path -LiteralPath $Settings).Path
$settingsValue = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
if ($settingsValue.backend -notin @('motioncraft', 'syntalker')) { throw 'Unknown backend.' }
if (!$Port) { $Port = if ($settingsValue.backend -eq 'motioncraft') { 18086 } else { 18087 } }
$paths = @($repo, (Join-Path $repo 'src'),
    (Join-Path $repo 'packages/contracts/src'), (Join-Path $repo 'packages/model_sdk/src'),
    (Join-Path $repo 'plugins/models/motioncraft-smplx/runtime/src'))
$previousPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = ($paths + @($previousPath) | Where-Object { $_ }) -join [IO.Path]::PathSeparator
    & $runtimePython -m scripts.character.unified_motion.server --settings $settingsPath --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Motion worker exited with code $LASTEXITCODE" }
} finally { $env:PYTHONPATH = $previousPath }
