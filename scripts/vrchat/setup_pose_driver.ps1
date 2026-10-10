[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SteamVR,
    [switch]$BuildOnly
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtime = Join-Path $repo '.virea-runtime/vrchat'
$revision = '0924064316de3effbcd1acf1e309182a2deb1c05'
$headers = Join-Path $runtime 'tools/openvr-0924064'
# Build-only checks must not write into an installed, possibly loaded driver.
$build = Join-Path $runtime $(if ($BuildOnly) { 'openvr-build-only' } else { 'openvr-build' })
$registryTool = Join-Path (Resolve-Path -LiteralPath $SteamVR).Path 'bin/win64/vrpathreg.exe'
if (!(Test-Path -LiteralPath $registryTool -PathType Leaf)) { throw 'Select the installed official SteamVR directory' }
if (!$BuildOnly -and (Get-Process vrserver -ErrorAction SilentlyContinue)) {
    throw 'Close SteamVR before replacing the driver registration. Existing game clients will not be closed by this script.'
}
New-Item -ItemType Directory -Path $headers -Force | Out-Null
$header = Join-Path $headers 'openvr_driver.h'
if (!(Test-Path -LiteralPath $header)) {
    Invoke-WebRequest "https://raw.githubusercontent.com/ValveSoftware/openvr/$revision/headers/openvr_driver.h" -OutFile $header
}
if ((Get-FileHash -LiteralPath $header -Algorithm SHA256).Hash -ne '1036EFE998D63E82D1D3DB2B32A2F58DF4A8EEAF5280F50AAF28220FF60A40AB') {
    throw 'OpenVR header checksum mismatch; do not build an unverified driver'
}
$license = Join-Path $headers 'LICENSE'
if (!(Test-Path -LiteralPath $license)) {
    Invoke-WebRequest "https://raw.githubusercontent.com/ValveSoftware/openvr/$revision/LICENSE" -OutFile $license
}
& cmake -S (Join-Path $repo 'integrations/vrchat/openvr') -B $build -A x64 "-DOPENVR_INCLUDE_DIR=$headers"
if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed; install Visual Studio C++ Build Tools and CMake' }
& cmake --build $build --config Release
if ($LASTEXITCODE -ne 0) { throw 'Driver build failed; close SteamVR if the existing DLL is locked' }
$driver = Join-Path $build 'driver'
if (!$BuildOnly) {
    & $registryTool removedriverswithname virea_pose
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove previous VIREA driver registration' }
    & $registryTool adddriver $driver
    if ($LASTEXITCODE -ne 0) { throw 'Could not register VIREA pose driver' }
}
Write-Output "Built: $driver. Start SteamVR, keep the observer in desktop mode, and start only the AI with start_ai_client.ps1 -VR."
