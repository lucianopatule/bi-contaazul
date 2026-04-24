# BI ContaAzul - Iniciar (uso diario via atalho)
$ROOT = Split-Path -Parent $PSScriptRoot
Push-Location $ROOT
Write-Host "BI ContaAzul - Iniciando..." -ForegroundColor Cyan
& .\.venv\Scripts\Activate.ps1
Start-Job -ScriptBlock { Start-Sleep 3; Start-Process "http://localhost:8000/" } | Out-Null
Write-Host "Abrira em http://localhost:8000/ (Ctrl+C para parar)" -ForegroundColor Yellow
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Pop-Location
