# Start FinAlly in Docker (idempotent). Usage: .\start_windows.ps1 [-Build] [-Open]
param([switch]$Build, [switch]$Open)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$Image = 'finally'; $Name = 'finally'; $Volume = 'finally-data'; $Url = 'http://localhost:8000'

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Warning '.env was missing; created from .env.example. Set OPENROUTER_API_KEY in .env for AI chat.'
}

$hasImage = [bool](docker images -q $Image)
if ($Build -or -not $hasImage) {
    Write-Host "Building image '$Image'..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { throw 'docker build failed' }
}

$running = docker ps --format '{{.Names}}' | Where-Object { $_ -eq $Name }
if ($running) {
    Write-Host 'FinAlly is already running.'
} else {
    $stale = docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq $Name }
    if ($stale) { docker rm -f $Name | Out-Null }
    docker run -d --name $Name -p 8000:8000 -v "${Volume}:/app/db" --env-file .env $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'docker run failed' }
    Write-Host 'FinAlly started.'
}

Write-Host "Open $Url"
if ($Open) { Start-Process $Url }
