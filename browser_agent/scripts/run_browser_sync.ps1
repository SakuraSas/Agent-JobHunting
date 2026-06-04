$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogDir "xiaomi_campus_browser_$Timestamp.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Push-Location $Root
try {
    & uv run python scripts/browser_sync_jobs.py --source xiaomi_campus_browser *>&1 |
        Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) {
        throw "Browser sync failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
