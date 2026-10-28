param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$Demo
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install requirements.txt first; see README.md.'
}
if ($Demo) {
    $env:REMNANTX_DB_PATH = Join-Path $projectRoot 'demo_warehouse.db'
    $env:REMNANTX_ARTIFACT_DIR = Join-Path $projectRoot 'artifacts\demo'
    Write-Host 'Separate demo database selected. Seeding remains an explicit API action.'
}
Set-Location -LiteralPath $projectRoot
Write-Host "Open http://127.0.0.1:$Port/docs"
& $pythonPath -m uvicorn backend.api:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
