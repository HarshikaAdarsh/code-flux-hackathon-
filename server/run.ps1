# Starts the backend using the project's virtualenv.
#
# Running a bare `uvicorn` picks up whichever uvicorn is first on PATH, which
# on this machine is a global install without the project's dependencies.
# Calling the venv's python directly avoids that entirely.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.\.venv\Scripts\python.exe')) {
    Write-Host 'No virtualenv found. Run:' -ForegroundColor Yellow
    Write-Host '  python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
    exit 1
}

# The database must be up before the API starts.
docker compose up -d | Out-Null

$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $procId = $busy[0].OwningProcess
    $name = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
    Write-Host "Port 8000 is already held by $name (PID $procId)." -ForegroundColor Yellow
    Write-Host "Stop it first:  Stop-Process -Id $procId -Force"
    exit 1
}

Write-Host 'API on http://127.0.0.1:8000  (docs at /docs)' -ForegroundColor Green
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
