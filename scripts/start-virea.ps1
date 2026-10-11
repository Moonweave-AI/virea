[CmdletBinding()]
param([string]$DataRoot = '', [int]$Port = 8000, [switch]$NoBrowser, [switch]$PrepareOnly, [switch]$SmokeTest)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (!$DataRoot) { $DataRoot = Join-Path $repo '.virea-runtime/portable' }
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$tools = Join-Path $DataRoot 'tools/uv'
New-Item -ItemType Directory -Path $tools -Force | Out-Null
$uv = Join-Path $tools 'uv.exe'
if (!(Test-Path -LiteralPath $uv)) {
    Write-Host '[VIREA 1/8] Installing the user-local runtime manager...'
    $installer = Join-Path $DataRoot 'install-uv.ps1'
    Invoke-WebRequest 'https://astral.sh/uv/0.10.9/install.ps1' -OutFile $installer -UseBasicParsing
    $env:UV_UNMANAGED_INSTALL = $tools
    & $installer
    if (!(Test-Path -LiteralPath $uv)) { throw 'uv installation failed. Check your network and retry.' }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $DataRoot 'tools/python'
$env:UV_CACHE_DIR = Join-Path $DataRoot 'cache/uv'
$env:PATH = "$tools;$env:PATH"
$arguments = @('run', '--no-project', '--python', '3.12', (Join-Path $PSScriptRoot 'setup/first_run.py'), '--data-root', $DataRoot, '--port', "$Port")
if ($NoBrowser) { $arguments += '--no-browser' }
if ($PrepareOnly) { $arguments += '--prepare-only' }
if ($SmokeTest) { $arguments += '--smoke-test' }
& $uv @arguments
exit $LASTEXITCODE
