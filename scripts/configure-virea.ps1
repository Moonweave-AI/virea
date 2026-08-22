[CmdletBinding()]
param(
    # The root of a user-selected data volume. VIREA creates only its own child directories below it.
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$DataRoot,

    # Keep this false for a real one-time setup. It exists for isolated validation and temporary automation.
    [switch]$NoPersistUserEnvironment
)

$ErrorActionPreference = "Stop"

function Test-PathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Parent
    )

    $trimChars = [char[]]@('\', '/')
    $candidatePath = [System.IO.Path]::GetFullPath($Candidate).TrimEnd($trimChars)
    $parentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd($trimChars)
    return $candidatePath.StartsWith(
        "$parentPath$([System.IO.Path]::DirectorySeparatorChar)",
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or $candidatePath.Equals($parentPath, [System.StringComparison]::OrdinalIgnoreCase)
}

$resolvedDataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (Test-PathWithin -Candidate $resolvedDataRoot -Parent $repositoryRoot) {
    throw "DataRoot must be outside the cloned repository: $repositoryRoot"
}

$layout = [ordered]@{
    schema_version          = "virea.persistent_data_root.v1"
    data_root               = $resolvedDataRoot
    virea_home              = Join-Path $resolvedDataRoot "home"
    uv_project_environment  = Join-Path $resolvedDataRoot "dev-venv"
    uv_cache_dir            = Join-Path $resolvedDataRoot "uv-cache"
    hf_home                 = Join-Path $resolvedDataRoot "home\cache\huggingface"
    npm_cache               = Join-Path $resolvedDataRoot "npm-cache"
    pnpm_store              = Join-Path $resolvedDataRoot "pnpm-store"
}

foreach ($directory in @(
    $layout.data_root,
    $layout.virea_home,
    $layout.uv_project_environment,
    $layout.uv_cache_dir,
    $layout.hf_home,
    $layout.npm_cache,
    $layout.pnpm_store
)) {
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
}

$settingsPath = Join-Path $layout.data_root "virea-environment.json"
$temporarySettingsPath = "$settingsPath.tmp-$PID"
$settingsJson = $layout | ConvertTo-Json
[System.IO.File]::WriteAllText(
    $temporarySettingsPath,
    $settingsJson,
    [System.Text.UTF8Encoding]::new($false)
)
Move-Item -LiteralPath $temporarySettingsPath -Destination $settingsPath -Force

$environment = [ordered]@{
    VIREA_HOME              = $layout.virea_home
    UV_PROJECT_ENVIRONMENT  = $layout.uv_project_environment
    UV_CACHE_DIR            = $layout.uv_cache_dir
    HF_HOME                 = $layout.hf_home
    NPM_CONFIG_CACHE        = $layout.npm_cache
    NPM_CONFIG_STORE_DIR    = $layout.pnpm_store
}
foreach ($entry in $environment.GetEnumerator()) {
    # Update this PowerShell process so the next command works immediately.
    Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
    if (-not $NoPersistUserEnvironment) {
        # Persist for future Windows Terminal, PowerShell and cmd.exe processes of this user.
        [System.Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "User")
    }
}

if (-not $NoPersistUserEnvironment) {
    # Notify already-running shells/terminal hosts that the user environment changed.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class VireaEnvironmentBroadcast {
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr hWnd, uint message, IntPtr wParam, string lParam,
        uint flags, uint timeout, out IntPtr result);
}
'@ -ErrorAction Stop
    $broadcastResult = [IntPtr]::Zero
    [void][VireaEnvironmentBroadcast]::SendMessageTimeout(
        [IntPtr]0xffff,
        0x001a,
        [IntPtr]::Zero,
        "Environment",
        0x0002,
        5000,
        [ref]$broadcastResult
    )
}

Write-Host "VIREA data root configured: $($layout.data_root)"
Write-Host "VIREA_HOME: $($layout.virea_home)"
Write-Host "uv environment: $($layout.uv_project_environment)"
Write-Host "uv cache: $($layout.uv_cache_dir)"
Write-Host "Hugging Face cache: $($layout.hf_home)"
Write-Host "npm cache: $($layout.npm_cache)"
Write-Host "pnpm store: $($layout.pnpm_store)"
if ($NoPersistUserEnvironment) {
    Write-Host "Current shell is ready. User-level settings were intentionally not changed."
} else {
    Write-Host "Current shell is ready. New terminals inherit the same user-level settings."
}
