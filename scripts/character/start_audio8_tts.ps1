[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$VireaHome,
    [Parameter(Mandatory)][string]$HfHome,
    [Parameter(Mandatory)][string]$Model,
    [string]$Distribution = 'Ubuntu-24.04',
    [string]$RuntimeRoot,
    [int]$Port = 8083,
    [int]$BackendPort = 8086,
    [ValidateRange(0.05, 0.95)][double]$MemoryFraction = 0.9
)
$ErrorActionPreference = 'Stop'
if (!$RuntimeRoot) {
    $RuntimeRoot = (& wsl.exe --distribution $Distribution --exec sh -lc 'printf "%s/.local/share/virea/audio8" "$HOME"' | Out-String).Trim()
}
function Convert-Audio8Path([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $converted = & wsl.exe --distribution $Distribution --exec wslpath -a -u $absolute
    if ($LASTEXITCODE -ne 0) { throw "Cannot map path into WSL: $absolute" }
    return ($converted | Out-String).Trim()
}
$script = Convert-Audio8Path (Join-Path $PSScriptRoot 'serve_audio8_tts.py')
$linuxHome = Convert-Audio8Path $VireaHome
$linuxCache = Convert-Audio8Path $HfHome
$linuxModel = Convert-Audio8Path $Model
& wsl.exe --distribution $Distribution --exec env "VIREA_HOME=$linuxHome" "HF_HOME=$linuxCache" `
    "$RuntimeRoot/venv/bin/python" $script --model $linuxModel --runtime-root $RuntimeRoot `
    --port "$Port" --backend-port "$BackendPort" --memory-fraction $MemoryFraction.ToString([Globalization.CultureInfo]::InvariantCulture)
if ($LASTEXITCODE -ne 0) { throw "Audio8-TTS exited with code $LASTEXITCODE" }
