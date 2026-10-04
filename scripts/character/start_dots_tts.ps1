[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$VireaHome,
    [Parameter(Mandatory)][string]$HfHome,
    [string]$Distribution = 'Ubuntu-24.04',
    [int]$Port = 8083,
    [ValidateSet('cpu', 'cuda')][string]$Device = 'cuda',
    [string]$Model = 'dots-studio/dots.tts-soar',
    [ValidateSet('none', 'nf4')][string]$Quantization,
    [ValidateRange(0.1, 1024)][double]$GpuMemoryGiB = 6,
    [switch]$Optimize
)
$ErrorActionPreference = 'Stop'

function Convert-WslPath([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $converted = & wsl.exe --distribution $Distribution --exec wslpath -a -u $absolute
    if ($LASTEXITCODE -ne 0) { throw "Cannot map path into WSL: $absolute" }
    return ($converted | Out-String).Trim()
}

# Official pynini wheels are Linux-only; keep the complete upstream runtime in WSL.
$script = Convert-WslPath (Join-Path $PSScriptRoot 'serve_dots_tts.py')
$linuxHome = Convert-WslPath $VireaHome
$linuxCache = Convert-WslPath $HfHome
if (Test-Path -LiteralPath $Model -PathType Container) { $Model = Convert-WslPath $Model }
$uv = (& wsl.exe --distribution $Distribution --exec sh -lc 'command -v uv' | Out-String).Trim()
if (!$uv -or $LASTEXITCODE -ne 0) { throw "Install uv in WSL distribution $Distribution before starting dots.tts." }
$launch = @('--distribution', $Distribution, '--exec', 'env', "VIREA_HOME=$linuxHome", "HF_HOME=$linuxCache",
    $uv, 'run', '--locked', '--script', $script, '--port', "$Port", '--device', $Device, '--model', $Model)
if ($Optimize) { $launch += '--optimize' }
if ($Quantization) { $launch += @('--quantization', $Quantization) }
$launch += @('--gpu-memory-gib', $GpuMemoryGiB.ToString([Globalization.CultureInfo]::InvariantCulture))
& wsl.exe @launch
if ($LASTEXITCODE -ne 0) { throw "dots.tts exited with code $LASTEXITCODE" }
