[CmdletBinding()]
param(
    [string]$Settings = (Join-Path $PSScriptRoot '../../.virea-runtime/vrchat/config/stack.json'),
    [string]$AvatarSource = (Join-Path $PSScriptRoot '../../.virea-runtime/vrchat/unity/avatar/Assets/VIREASetup/VireaSource.vrm'),
    [string]$VRChatExe,
    [ValidateRange(0, 99)][int]$AIProfile = 2,
    [switch]$VR,
    [switch]$SkipWebBuild
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$stack = Get-Content -LiteralPath $Settings -Raw | ConvertFrom-Json
if (!$PSBoundParameters.ContainsKey('AIProfile') -and $null -ne $stack.ai_client.profile) {
    $AIProfile = [int]$stack.ai_client.profile
}
if (!$PSBoundParameters.ContainsKey('VR') -and $null -ne $stack.ai_client.vr) {
    $VR = [bool]$stack.ai_client.vr
}
$sendPort = if ($null -ne $stack.ai_client.send_port) { [int]$stack.ai_client.send_port } else { 19010 }
$receivePort = if ($null -ne $stack.ai_client.receive_port) { [int]$stack.ai_client.receive_port } else { 19011 }
if ($sendPort -eq $receivePort -or $sendPort -in @(9000, 9001) -or $receivePort -in @(9000, 9001) -or
    $sendPort -lt 1024 -or $sendPort -gt 65535 -or $receivePort -lt 1024 -or $receivePort -gt 65535) {
    throw 'Configure distinct AI ports between 1024 and 65535; 9000/9001 belong to the observer'
}
$api = @($stack.services | Where-Object name -eq 'api')
if ($api.Count -ne 1) { throw 'The stack must define exactly one api service' }
$runtimeRoot = [IO.Path]::GetFullPath([string]$api[0].environment.VIREA_HOME)
if (!$runtimeRoot.StartsWith($repo + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'VIREA_HOME must stay inside this project'
}
if (Test-Path -LiteralPath $AvatarSource -PathType Leaf) {
    $avatarDirectory = Join-Path $runtimeRoot 'avatars'
    New-Item -ItemType Directory -Path $avatarDirectory -Force | Out-Null
    Copy-Item -LiteralPath $AvatarSource -Destination (Join-Path $avatarDirectory 'vrchat.vrm') -Force
}
if (!$SkipWebBuild) {
    Push-Location (Join-Path $repo 'apps/web')
    try { & npm run build; if ($LASTEXITCODE -ne 0) { throw 'Web build failed' } } finally { Pop-Location }
}
& (Join-Path $PSScriptRoot 'start.ps1') -Settings $Settings
if ($VRChatExe) {
    $running = @(Get-NetUDPEndpoint -LocalPort $sendPort -ErrorAction SilentlyContinue)
    if (!$running.Count) {
        & (Join-Path $PSScriptRoot 'start_ai_client.ps1') -VRChatExe $VRChatExe -Profile $AIProfile -SendPort $sendPort -ReceivePort $receivePort -VR:$VR
    } else {
        $ownerIds = @($running | Select-Object -ExpandProperty OwningProcess -Unique)
        if ($ownerIds.Count -ne 1 -or (Get-Process -Id $ownerIds[0]).ProcessName -ne 'VRChat') {
            throw "AI port $sendPort is occupied by another application"
        }
        Write-Output 'AI VRChat client is already running; preserving both account windows.'
    }
}
Write-Output "Services ready: $($stack.ui). The page restores its connection automatically; game login, VR tracking calibration and visual acceptance are separate checks."
