param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8001,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebRoot = Join-Path $ProjectRoot "langchain_agent"
$EnvPath = Join-Path $WebRoot ".env"
$EmbeddingModel = Join-Path $ProjectRoot "bge-small\bge-small-zh-v1.5"

function Fail($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Info($Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

if (-not (Test-Path $WebRoot)) {
    Fail "Cannot find langchain_agent directory: $WebRoot"
}

if (-not (Test-Path (Join-Path $WebRoot "pyproject.toml"))) {
    Fail "Cannot find pyproject.toml under: $WebRoot"
}

if (-not (Test-Path $EnvPath)) {
    Fail "Cannot find .env: $EnvPath"
}

if (-not (Test-Path $EmbeddingModel)) {
    Fail "Cannot find local embedding model: $EmbeddingModel"
}

$env:EMBEDDING_MODEL = $EmbeddingModel.Replace("\", "/")
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

$PortProcess = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" } |
    Select-Object -First 1

if ($PortProcess) {
    $PidOnPort = $PortProcess.OwningProcess
    if ($Force) {
        Info "Port $Port is occupied by PID $PidOnPort. Stopping it because -Force was provided."
        Stop-Process -Id $PidOnPort -Force
        Start-Sleep -Seconds 1
    }
    else {
        Fail "Port $Port is already in use by PID $PidOnPort. Run with -Force to stop it, or choose another -Port."
    }
}

Info "Project root: $ProjectRoot"
Info "Web root: $WebRoot"
Info "Embedding model: $env:EMBEDDING_MODEL"
Info "Starting Web UI at http://$HostName`:$Port"

Push-Location $WebRoot
try {
    uv run python -m uvicorn job_agent.web:app --host $HostName --port $Port
}
finally {
    Pop-Location
}
