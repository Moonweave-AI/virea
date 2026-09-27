[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$VireaHome,
    [Parameter(Mandatory)][string]$LlamaServer,
    [Parameter(Mandatory)][string]$ModelFile,
    [Parameter(Mandatory)][string]$HfHome,
    [string]$MotionPlannerFile,
    [switch]$SkipWarmup
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path $repo '.venv/Scripts/python.exe'
foreach ($file in @($python, $LlamaServer, $ModelFile)) {
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing file: $file" }
}
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is already running. Stop that API before starting the GPU configuration.'
}
$logs = Join-Path $VireaHome 'logs/character-stack'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$started = @()

function Start-Helper([string]$Name, [string]$Executable, [string[]]$Arguments) {
    # Quote complete Windows arguments; do not invoke a second shell.
    $quoted = @($Arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' })
    $process = Start-Process -FilePath $Executable -ArgumentList $quoted -WorkingDirectory $repo `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "$Name.out.log") `
        -RedirectStandardError (Join-Path $logs "$Name.err.log") -PassThru
    return @{ name = $Name; pid = $process.Id; started = $process.StartTime.ToUniversalTime().ToString('o'); executable = $Executable }
}

function Wait-Endpoint([string]$Url, [int]$Seconds = 180) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try { return Invoke-RestMethod -Uri $Url -TimeoutSec 2 }
        catch { Start-Sleep -Milliseconds 300 }
    } while ((Get-Date) -lt $deadline)
    throw "Readiness timeout: $Url. Inspect $logs"
}

if (!(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue)) {
    $started += Start-Helper 'language' $LlamaServer @('-m', $ModelFile, '--alias', 'qwen3.5:9b',
        '--host', '127.0.0.1', '--port', '8080', '-ngl', '99', '-c', '8192', '-np', '1',
        '-fa', 'on', '-ctk', 'q8_0', '-ctv', 'q8_0', '--reasoning', 'on', '--reasoning-budget', '96',
        '--no-prefill-assistant', '-t', '8')
}
$models = Wait-Endpoint 'http://127.0.0.1:8080/v1/models'
if ('qwen3.5:9b' -notin $models.data.id) { throw 'Port 8080 must serve qwen3.5:9b.' }
if (!$MotionPlannerFile) { $MotionPlannerFile = Join-Path (Split-Path $ModelFile) 'sentiavatar-planner-f16.gguf' }
if (!(Test-Path -LiteralPath $MotionPlannerFile -PathType Leaf)) {
    throw 'Prepare the motion planner with scripts/character/build_motion_planner.py first.'
}
if (!(Get-NetTCPConnection -LocalPort 8084 -State Listen -ErrorAction SilentlyContinue)) {
    $started += Start-Helper 'motion-planner' $LlamaServer @('-m', $MotionPlannerFile,
        '--alias', 'sentiavatar-planner', '--host', '127.0.0.1', '--port', '8084',
        '-ngl', '99', '-c', '4096', '-np', '1', '-fa', 'on', '-t', '4', '--no-webui')
}
$plannerModels = Wait-Endpoint 'http://127.0.0.1:8084/v1/models'
if ('sentiavatar-planner' -notin $plannerModels.data.id) { throw 'Port 8084 must serve sentiavatar-planner.' }
$env:HF_HOME = $HfHome
if (!(Get-NetTCPConnection -LocalPort 8083 -State Listen -ErrorAction SilentlyContinue)) {
    $started += Start-Helper 'speech' (Get-Command uv).Source @('run', '--locked', '--script',
        (Join-Path $PSScriptRoot 'serve_kokoro_cuda.py'), '--port', '8083', '--precision', 'auto')
}
$speech = Wait-Endpoint 'http://127.0.0.1:8083/health' 1200
if ($speech.device -ne 'cuda' -or $speech.precision -ne 'auto') { throw 'Port 8083 must serve CUDA adaptive-precision Kokoro.' }
$env:VIREA_HOME = $VireaHome
$env:VIREA_CHARACTER_CONFIG = Join-Path $repo 'configs/character/rtx5090.json'
$env:PYTHONIOENCODING = 'utf-8'
& $python (Join-Path $PSScriptRoot 'build_neutral_pose.py') --home $VireaHome
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the licensed neutral pose reference.' }
$started += Start-Helper 'api' $python @('-m', 'uvicorn', 'virea_api.app:app', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'warning')
$started | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $logs 'started-processes.json') -Encoding utf8
Wait-Endpoint 'http://127.0.0.1:8000/api/v1/health' | Out-Null
if (!$SkipWarmup) {
    Write-Output 'Prewarming language, speech and motion. No expression is played or acknowledged.'
    $session = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/characters' -Method Post -ContentType application/json -Body '{}'
    try {
        $url = "http://127.0.0.1:8000/api/v1/characters/$($session.id)"
        $body = @{ text = '只说：你好。说完等待。' } | ConvertTo-Json
        Invoke-RestMethod "$url/messages" -Method Post -ContentType application/json -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
        $deadline = (Get-Date).AddMinutes(5)
        do {
            $state = Invoke-RestMethod $url
            if ($state.status -eq 'error') { throw ($state.events[-1].message) }
            if ($state.pending.motion) { break }
            Start-Sleep -Milliseconds 300
        } while ((Get-Date) -lt $deadline)
        if (!$state.pending.motion) { throw 'Motion prewarm timed out.' }
    } finally { Invoke-RestMethod $url -Method Delete | Out-Null }
}
Write-Output "Ready: http://127.0.0.1:8000/app/character.html. Logs and owned process IDs: $logs"
