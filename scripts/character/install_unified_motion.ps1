[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('motioncraft', 'syntalker')][string]$Backend,
    [Parameter(Mandatory)][string]$DataRoot,
    [ValidateSet('cpu', 'cuda')][string]$Device = 'cuda'
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$root = [IO.Path]::GetFullPath((Join-Path $DataRoot $Backend))
New-Item -ItemType Directory -Path $root -Force | Out-Null
if ($Backend -eq 'motioncraft') {
    $runtime = Join-Path $repo $(if ($Device -eq 'cuda') { 'plugins/models/motioncraft-smplx/runtime-cu128' } else { 'plugins/models/motioncraft-smplx/runtime-cpu' })
    $workerPython = Join-Path $runtime '.venv/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $workerPython)) { & uv venv --python 3.11 (Join-Path $runtime '.venv') }
    if ($LASTEXITCODE -ne 0) { throw 'MotionCraft environment creation failed.' }
    & uv pip install --python $workerPython 'setuptools<81' wheel
    if ($LASTEXITCODE -ne 0) { throw 'MMCV build dependencies installation failed.' }
    & uv sync --project $runtime --locked --inexact --no-build-isolation-package mmcv
    if ($LASTEXITCODE -ne 0) { throw 'MotionCraft runtime installation failed.' }
    & uv pip install --python $workerPython 'gdown>=5,<6' 'setuptools<81'
} else {
    $runtime = Join-Path $root 'runtime'
    $workerPython = Join-Path $runtime 'Scripts/python.exe'
    if (!(Test-Path -LiteralPath $workerPython)) { & uv venv --python 3.11 $runtime }
    if ($LASTEXITCODE -ne 0) { throw 'SynTalker environment creation failed.' }
    $index = if ($Device -eq 'cuda') { 'https://download.pytorch.org/whl/cu128' } else { 'https://download.pytorch.org/whl/cpu' }
    & uv pip install --python $workerPython 'torch==2.11.0' --index-url $index
    if ($LASTEXITCODE -ne 0) { throw 'SynTalker PyTorch installation failed.' }
    & uv pip install --python $workerPython -r (Join-Path $PSScriptRoot 'requirements-syntalker.txt') 'huggingface-hub>=0.34,<1'
}
if ($LASTEXITCODE -ne 0) { throw 'Motion dependencies installation failed.' }
$previousPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$repo;$repo/src;$previousPath"
    & $workerPython -m scripts.character.unified_motion.prepare $Backend --root $root --device $Device
    if ($LASTEXITCODE -ne 0) { throw 'Official model asset preparation failed.' }
} finally { $env:PYTHONPATH = $previousPath }
Write-Output "Python: $workerPython"
Write-Output "Settings: $(Join-Path $root 'worker.json')"
Write-Output "Start: ./scripts/character/start_unified_motion.ps1 -Python '$workerPython' -Settings '$(Join-Path $root 'worker.json')'"
