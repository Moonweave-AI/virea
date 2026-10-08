[CmdletBinding()]
param(
    [string]$Project = (Join-Path $PSScriptRoot '../../.virea-runtime/vrchat/unity/avatar'),
    [Parameter(Mandatory)][string]$UnityEditor,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath $Project).Path
$unityExe = (Resolve-Path -LiteralPath $UnityEditor).Path
if ((Get-Item -LiteralPath $unityExe).VersionInfo.ProductVersion -notlike '2022.3.22f1*') { throw 'VRChat requires Unity 2022.3.22f1 for this project' }
$logs = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../.virea-runtime/vrchat/logs'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$scene = Join-Path $projectRoot 'Assets/VIREA/Scenes/IndependentAI.unity'
if ($ValidateOnly -and !(Test-Path -LiteralPath $scene)) { throw 'No prepared scene exists' }
if (!$ValidateOnly -and (Test-Path -LiteralPath $scene)) { throw 'Prepared scene already exists; use -ValidateOnly or preserve it before regenerating' }
$steps = @(@{method='VRC.Editor.EnvConfig.SetActiveSDKDefines'; name='unity-sdk'; quit=$true})
$steps += @{method=('Virea.VRChat.Editor.VireaProjectSetup.' + $(if ($ValidateOnly) {'Validate'} else {'Prepare'})); name='unity-avatar'; quit=[bool]$ValidateOnly}
foreach ($step in $steps) {
    $logPath = Join-Path $logs ($step.name + '.log')
    $arguments = @('-batchmode','-nographics','-accept-apiupdate','-projectPath',('"' + $projectRoot + '"'),'-executeMethod',$step.method,'-logFile',('"' + $logPath + '"'))
    if ($step.quit) { $arguments += '-quit' }
    $process = Start-Process -FilePath $unityExe -ArgumentList $arguments -WindowStyle Hidden -PassThru
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Unity failed ($($process.ExitCode)); inspect $logPath" }
}
$log = Get-Content -LiteralPath (Join-Path $logs 'unity-avatar.log') -Raw
if ($log -notmatch 'VIREA_AVATAR_VALIDATED:') { throw 'Unity exited without confirming avatar validation' }
Write-Output "Avatar scene validated: $scene. Open this scene for SDK Build & Test. No upload performed."
