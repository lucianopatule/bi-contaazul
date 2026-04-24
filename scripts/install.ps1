# BI ContaAzul - Instalador local
# Rodar de dentro da pasta do projeto: .\scripts\install.ps1

$ErrorActionPreference = 'Stop'
$ROOT = Split-Path -Parent $PSScriptRoot
Push-Location $ROOT

function Write-Header($t) {
    Write-Host "`n---- $t ----" -ForegroundColor Magenta
}

function Find-Psql {
    $c = @(
        "D:\Program Files\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files\PostgreSQL\16\bin\psql.exe",
        "D:\Program Files\PostgreSQL\15\bin\psql.exe",
        "C:\Program Files\PostgreSQL\15\bin\psql.exe"
    )
    foreach ($p in $c) { if (Test-Path $p) { return $p } }
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Path }
    return $null
}

Write-Header "Criando ambiente Python"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\pip.exe install -r requirements.txt --quiet
Write-Host "OK: dependencias instaladas" -ForegroundColor Green

Write-Header "Configurando PostgreSQL"
$psql = Find-Psql
if (-not $psql) {
    Write-Host "ERRO: psql nao encontrado" -ForegroundColor Red
    Pop-Location; exit 1
}
$pg_user = Read-Host "Usuario PostgreSQL (default: postgres)"
if ([string]::IsNullOrWhiteSpace($pg_user)) { $pg_user = "postgres" }
$pg_pass_sec = Read-Host "Senha do $pg_user" -AsSecureString
$pg_pass = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pg_pass_sec))
$env:PGPASSWORD = $pg_pass

$exists = & $psql -h 127.0.0.1 -U $pg_user -tAc "SELECT 1 FROM pg_database WHERE datname='bi_conta_azul'" 2>$null
if ($exists -ne '1') {
    & $psql -h 127.0.0.1 -U $pg_user -c "CREATE DATABASE bi_conta_azul;"
}
& $psql -h 127.0.0.1 -U $pg_user -d bi_conta_azul -f schema.sql -q
Write-Host "OK: database e schema prontos" -ForegroundColor Green

Write-Header "Configurando .env"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$key = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env_content = Get-Content .env
$env_content = $env_content -replace '^CRYPTO_MASTER_KEY=.*$', "CRYPTO_MASTER_KEY=$key"
$env_content = $env_content -replace '^DB_USER=.*$',          "DB_USER=$pg_user"
$env_content = $env_content -replace '^DB_PASSWORD=.*$',      "DB_PASSWORD=$pg_pass"
$env_content | Set-Content .env
Write-Host "OK: chave de criptografia gerada" -ForegroundColor Green

Write-Host ""
Write-Host "Agora vamos configurar suas credenciais do ContaAzul." -ForegroundColor Cyan
Write-Host "Se ja criou o app em developers.contaazul.com, tenha client_id e client_secret em maos." -ForegroundColor Cyan
$cid = Read-Host "CA_CLIENT_ID (vazio para preencher depois no .env)"
if (-not [string]::IsNullOrWhiteSpace($cid)) {
    $cs_sec = Read-Host "CA_CLIENT_SECRET" -AsSecureString
    $cs = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($cs_sec))
    $env_content = Get-Content .env
    $env_content = $env_content -replace '^CA_CLIENT_ID=.*$',     "CA_CLIENT_ID=$cid"
    $env_content = $env_content -replace '^CA_CLIENT_SECRET=.*$', "CA_CLIENT_SECRET=$cs"
    $env_content | Set-Content .env
    Write-Host "OK: credenciais ContaAzul gravadas" -ForegroundColor Green
}

Write-Header "Criando atalho no Desktop"
$desk = [Environment]::GetFolderPath("Desktop")
$lnk = "$desk\BI ContaAzul.lnk"
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = "powershell.exe"
$s.Arguments = "-ExecutionPolicy Bypass -NoExit -File `"$ROOT\scripts\start.ps1`""
$s.WorkingDirectory = $ROOT
$s.IconLocation = "imageres.dll,110"
$s.Description = "BI ContaAzul - PED Intelligence"
$s.Save()
Write-Host "OK: atalho 'BI ContaAzul' criado no Desktop" -ForegroundColor Green

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host " INSTALACAO CONCLUIDA" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host " Clique 2x no atalho 'BI ContaAzul' no Desktop" -ForegroundColor Yellow
Write-Host " O navegador abrira em http://localhost:8000/" -ForegroundColor Yellow
Write-Host ""
$go = Read-Host "Iniciar agora? (S/N)"
if ($go -match '^[Ss]') { & "$ROOT\scripts\start.ps1" }
Pop-Location
