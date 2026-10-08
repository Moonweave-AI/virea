[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$VRChatExe,
    [ValidateRange(0, 99)][int]$Profile = 2,
    [ValidateRange(1024, 65535)][int]$SendPort = 19010,
    [ValidateRange(1024, 65535)][int]$ReceivePort = 19011
)
$ErrorActionPreference = 'Stop'
$game = (Resolve-Path -LiteralPath $VRChatExe).Path
if ((Split-Path $game -Leaf) -ne 'VRChat.exe') { throw 'Select the installed official VRChat.exe' }
$launcher = Join-Path (Split-Path $game) 'launch.exe'
if (!(Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw 'The official launch.exe is missing beside VRChat.exe. Repair VRChat through Steam before online use; direct VRChat.exe starts offline testing mode.'
}
if ($SendPort -eq $ReceivePort -or $SendPort -in @(9000, 9001) -or $ReceivePort -in @(9000, 9001)) { throw 'Use separate AI ports; 9000/9001 belong to the observer' }
if (Get-NetUDPEndpoint -LocalPort $SendPort -ErrorAction SilentlyContinue) { throw "AI input port $SendPort is already in use; do not launch a duplicate client" }
foreach ($client in Get-CimInstance Win32_Process -Filter "Name='VRChat.exe'") {
    if ($client.CommandLine -match ('(?:^|\s|")--profile={0}(?:\s|"|$)' -f $Profile) -or
        ($Profile -eq 0 -and $client.CommandLine -notmatch '--profile=')) {
        throw "Profile $Profile is already running (PID $($client.ProcessId)); use that window or select another profile. No existing client was closed."
    }
}
# This is an interactive game window the user explicitly requested, not a hidden helper.
$launchArguments = @(
    '--no-vr', "--profile=$Profile", "--osc=${SendPort}:127.0.0.1:${ReceivePort}",
    '--watch-avatars', '--watch-worlds', '-screen-width', '1280', '-screen-height', '720', '-screen-fullscreen', '0'
)
if ($PSCmdlet.ShouldProcess("$launcher $($launchArguments -join ' ')", 'Launch protected online VRChat client')) {
    $process = Start-Process -FilePath $launcher -WorkingDirectory (Split-Path $game) -ArgumentList $launchArguments -PassThru
    Write-Output "Official launcher started (PID $($process.Id)), profile $Profile. Confirm the dedicated AI account in that window before enabling OSC output. Launcher startup alone does not confirm online connectivity."
}
