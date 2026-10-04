[CmdletBinding()]
param([Parameter(Mandatory)][string]$DataRoot)
$ErrorActionPreference = 'Stop'
$spec = Get-Content (Join-Path $PSScriptRoot 'spatial/models.json') -Raw | ConvertFrom-Json
$source = Join-Path $DataRoot 'research/ardy'
$runtime = Join-Path $DataRoot 'runtimes/ardy'
$python = Join-Path $runtime 'Scripts/python.exe'
if (!(Test-Path -LiteralPath $source)) {
    git clone $spec.source.url $source
    if ($LASTEXITCODE -ne 0) { throw 'ARDY checkout failed' }
    git -C $source checkout --detach $spec.source.revision
}
if ((git -C $source rev-parse HEAD) -ne $spec.source.revision) { throw 'ARDY source differs from the pinned revision' }
if (!(Test-Path -LiteralPath $python)) { uv venv --python 3.11 $runtime }
uv pip install --python $python 'torch==2.8.0' --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw 'CUDA Torch installation failed' }
uv pip install --python $python -r (Join-Path $PSScriptRoot 'spatial/requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Spatial dependencies failed' }
uv pip install --python $python --no-deps $source
if ($LASTEXITCODE -ne 0) { throw 'ARDY native contact solver build failed; install CMake and MSVC C++ tools' }
foreach ($item in @($spec.motion, $spec.text)) {
    hf download $item.repository --revision $item.revision --local-dir (Join-Path $DataRoot "models/$($item.directory)")
    if ($LASTEXITCODE -ne 0) { throw 'Pinned model download failed' }
}
Write-Output "Installed spatial runtime under $runtime"
