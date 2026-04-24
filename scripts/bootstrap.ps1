# BI ContaAzul - Bootstrap (Entry Point)
# PED Intelligence / JF Consultoria
#
# Uso na maquina de destino (PowerShell como Administrador):
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   iwr -useb https://raw.githubusercontent.com/lucianopatule/bi-contaazul/main/scripts/bootstrap.ps1 | iex

$ErrorActionPreference = 'Stop'
$REPO_URL = 'https://github.com/lucianopatule/bi-contaazul.git'
$INSTALL_DIR = 'C:\bi_contaazul'

function Write-Header($txt) {
    Write-Host "`n==============================================" -ForegroundColor Cyan
    Write-Host " $txt" -ForegroundColor Cyan
    Write-Host "==============================================" -ForegroundColor Cyan
}

function Test-Admin {
    $p = New-Object System.Security.Principal.WindowsPrincipal([System.Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-Cmd($c) { return [bool](Get-Command $c -ErrorAction SilentlyContinue) }

Write-Header "BI ContaAzul - Instalador Automatico"

if (-not (Test-Admin)) {
    Write-Host "ATENCAO: precisa rodar como Administrador." -ForegroundColor Yellow
    Read-Host "ENTER para sair"; exit 1
}

Write-Header "Checando pre-requisitos"
$miss = @()
if (-not (Test-Cmd git))    { $miss += 'Git.Git' }
if (-not (Test-Cmd python)) { $miss += 'Python.Python.3.11' }
$hasPg = (Test-Path "D:\Program Files\PostgreSQL\16\bin\psql.exe") -or `
         (Test-Path "C:\Program Files\PostgreSQL\16\bin\psql.exe") -or `
         (Test-Cmd psql)
if (-not $hasPg) { $miss += 'PostgreSQL.PostgreSQL.16' }

if ($miss.Count -gt 0) {
    Write-Host "Faltando:" -ForegroundColor Yellow
    $miss | ForEach-Object { Write-Host "  - $_" }
    $r = Read-Host "Instalar via winget? (S/N)"
    if ($r -match '^[Ss]') {
        foreach ($p in $miss) {
            Write-Host "Instalando $p..." -ForegroundColor Cyan
            winget install --id $p --silent --accept-source-agreements --accept-package-agreements
        }
        Write-Host "OK. FECHE e REABRA o PowerShell como admin, depois rode o bootstrap de novo." -ForegroundColor Green
        Read-Host "ENTER para sair"; exit 0
    } else { exit 1 }
}
Write-Host "OK: pre-requisitos presentes" -ForegroundColor Green

Write-Header "Obtendo codigo do GitHub"
if (Test-Path $INSTALL_DIR) {
    Push-Location $INSTALL_DIR; git pull origin main; Pop-Location
} else {
    git clone $REPO_URL $INSTALL_DIR
}

Write-Header "Executando instalador da aplicacao"
& "$INSTALL_DIR\scripts\install.ps1"
