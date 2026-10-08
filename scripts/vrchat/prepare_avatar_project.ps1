[CmdletBinding()]
param([Parameter(Mandatory)][string]$Project, [Parameter(Mandatory)][string]$VRM)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath $Project).Path
$model = (Resolve-Path -LiteralPath $VRM).Path
if ([IO.Path]::GetExtension($model) -ne '.vrm') { throw 'Select a VRM file' }
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'ProjectSettings/ProjectVersion.txt'))) { throw 'Create an Avatars project in Creator Companion first' }
$sdk = Join-Path $projectRoot 'Packages/com.vrchat.avatars'
if (!(Test-Path -LiteralPath $sdk)) { throw 'The project must contain the VRChat Avatars SDK' }
$destination = Join-Path $projectRoot 'Assets/VIREASetup'
$editor = Join-Path $destination 'Editor'
New-Item -ItemType Directory -Path $editor -Force | Out-Null
$sources = @(@{source = $model; target = (Join-Path $destination 'VireaSource.vrm')})
$editorSource = (Resolve-Path (Join-Path $PSScriptRoot '../../integrations/vrchat/unity/Editor')).Path
foreach ($sourceFile in Get-ChildItem -LiteralPath $editorSource -File) {
    if ($sourceFile.Extension -in @('.cs', '.asmdef')) {
        $sources += @{source = $sourceFile.FullName; target = (Join-Path $editor $sourceFile.Name)}
    }
}
foreach ($item in $sources) {
    if (Test-Path -LiteralPath $item.target) {
        if ((Get-FileHash -LiteralPath $item.source).Hash -ne (Get-FileHash -LiteralPath $item.target).Hash) { throw "Destination already differs: $($item.target). Preserve or rename it before importing." }
    } else { Copy-Item -LiteralPath $item.source -Destination $item.target }
}
Write-Output 'Source VRM and editor tools prepared locally. Install the pinned SDK/converter dependencies, then run build_avatar.ps1 or prepare the avatar in Unity. No upload has been performed.'
