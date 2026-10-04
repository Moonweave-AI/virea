[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$VireaHome,
    [Parameter(Mandatory)][string]$LlamaServer,
    [Parameter(Mandatory)][string]$ModelFile,
    [Parameter(Mandatory)][string]$HfHome,
    [string]$MotionPlannerFile,
    [ValidateSet('sentiavatar_ardy', 'motioncraft', 'syntalker')][string]$MotionBackend = 'sentiavatar_ardy',
    [string]$MotionPython,
    [string]$MotionSettings,
    [int]$ReasoningBudget = 512,
    [int]$ContextPerSlot = 16384,
    [int]$ParallelSlots = 2,
    [string]$SpeechDistribution = 'Ubuntu-24.04',
    [ValidateRange(0.05, 0.95)][double]$SpeechMemoryFraction = 0.9,
    [string]$SpeechModel,
    [switch]$SkipWarmup
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ($MotionBackend -ne 'sentiavatar_ardy') {
    foreach ($file in @($MotionPython, $MotionSettings)) {
        if (!$file -or !(Test-Path -LiteralPath $file -PathType Leaf)) { throw 'Unified motion requires -MotionPython and -MotionSettings from install_unified_motion.ps1.' }
    }
    $workerSettings = Get-Content -LiteralPath $MotionSettings -Raw | ConvertFrom-Json
    if ($workerSettings.backend -ne $MotionBackend) { throw 'Motion settings do not match the selected backend.' }
}
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
        '--host', '127.0.0.1', '--port', '8080', '-ngl', '99', '-c', "$($ContextPerSlot * $ParallelSlots)", '-np', "$ParallelSlots",
        '-fa', 'on', '-ctk', 'q8_0', '-ctv', 'q8_0', '--reasoning', 'auto', '--reasoning-budget', "$ReasoningBudget",
        '--no-prefill-assistant', '-t', '8')
}
$models = Wait-Endpoint 'http://127.0.0.1:8080/v1/models'
if ('qwen3.5:9b' -notin $models.data.id) { throw 'Port 8080 must serve qwen3.5:9b.' }
if ($MotionBackend -eq 'sentiavatar_ardy') {
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
} else {
    $motionPort = if ($MotionBackend -eq 'motioncraft') { 18086 } else { 18087 }
    if (!(Get-NetTCPConnection -LocalPort $motionPort -State Listen -ErrorAction SilentlyContinue)) {
        $started += Start-Helper $MotionBackend (Get-Process -Id $PID).Path @('-NoProfile', '-File',
            (Join-Path $PSScriptRoot 'start_unified_motion.ps1'), '-Python', $MotionPython,
            '-Settings', $MotionSettings, '-Port', "$motionPort")
    }
    $motion = Wait-Endpoint "http://127.0.0.1:$motionPort/health" 1200
    if ($motion.backend -ne $MotionBackend -or !$motion.ready -or !$motion.native_history -or !$motion.temporal_conditioning) {
        throw 'Motion worker identity or independent-track capability mismatch.'
    }
}
$env:HF_HOME = $HfHome
if (!$SpeechModel) { $SpeechModel = Join-Path (Split-Path $ModelFile) 'audio8-tts-0.6b' }
if (!(Get-NetTCPConnection -LocalPort 8083 -State Listen -ErrorAction SilentlyContinue)) {
    $started += Start-Helper 'speech' (Get-Process -Id $PID).Path @('-NoProfile', '-File',
        (Join-Path $PSScriptRoot 'start_audio8_tts.ps1'), '-VireaHome', $VireaHome,
        '-HfHome', $HfHome, '-Distribution', $SpeechDistribution, '-Port', '8083',
        '-Model', $SpeechModel,
        '-MemoryFraction', $SpeechMemoryFraction.ToString([Globalization.CultureInfo]::InvariantCulture))
}
$speech = Wait-Endpoint 'http://127.0.0.1:8083/health' 1200
if ($speech.provider -ne 'audio8-tts' -or $speech.device -ne 'cuda' -or $speech.sample_rate -ne 44100) {
    throw 'Port 8083 must serve CUDA Audio8-TTS at 44.1 kHz. Stop the old speech service before migrating.'
}
$env:VIREA_HOME = $VireaHome
if ($MotionBackend -eq 'sentiavatar_ardy') {
& (Join-Path $PSScriptRoot 'start_spatial.ps1') -DataRoot (Split-Path (Split-Path $ModelFile))
Wait-Endpoint 'http://127.0.0.1:8085/health' | Out-Null
$env:VIREA_CHARACTER_CONFIG = Join-Path $repo 'configs/character/rtx5090.json'
$env:PYTHONIOENCODING = 'utf-8'
& $python (Join-Path $PSScriptRoot 'build_neutral_pose.py') --home $VireaHome
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the licensed neutral pose reference.' }
} else {
    $env:VIREA_CHARACTER_CONFIG = Join-Path $repo "configs/character/$MotionBackend.json"
    $env:PYTHONIOENCODING = 'utf-8'
}
$started += Start-Helper 'api' $python @('-m', 'uvicorn', 'virea_api.app:app', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'warning')
$started | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $logs 'started-processes.json') -Encoding utf8
Wait-Endpoint 'http://127.0.0.1:8000/api/v1/health' | Out-Null
if (!$SkipWarmup -and $speech.voices -gt 0) {
    Write-Output 'Prewarming language, speech and motion. No expression is played or acknowledged.'
    $session = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/characters' -Method Post -ContentType application/json -Body '{}'
    try {
        $url = "http://127.0.0.1:8000/api/v1/characters/$($session.id)"
        $body = @{ text = '只说：你好，很高兴认识你。说完等待。' } | ConvertTo-Json
        Invoke-RestMethod "$url/messages" -Method Post -ContentType application/json -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
        $deadline = (Get-Date).AddMinutes(5)
        do {
            $state = Invoke-RestMethod $url
            if ($state.status -eq 'error') { throw ($state.events[-1].message) }
            if ($state.pending.motion -or $state.pending.performance) { break }
            Start-Sleep -Milliseconds 300
        } while ((Get-Date) -lt $deadline)
        if (!$state.pending.motion -and !$state.pending.performance) { throw 'Motion prewarm timed out.' }
    } finally { Invoke-RestMethod $url -Method Delete | Out-Null }
}
if (!$speech.voices) { Write-Output 'Import reference audio and its transcript in Settings before generating speech.' }
Write-Output "Ready: http://127.0.0.1:8000/app/character.html. Logs and owned process IDs: $logs"
