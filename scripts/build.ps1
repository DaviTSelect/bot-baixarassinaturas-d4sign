param(
    [switch]$ExecutableOnly
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

$appVersion = & venv\Scripts\python.exe -c "from d4sign.version import VERSION; print(VERSION)"
if ($LASTEXITCODE -ne 0) { throw 'Falha ao ler a versao.' }

$exeName = "BaixarAssinaturasD4sign v$appVersion"

Write-Host ""
Write-Host "Versao: $appVersion"
Write-Host "Nome do executavel: $exeName"
Write-Host ""

Write-Host "Limpando builds anteriores..."
if (Test-Path "dist")  { Remove-Item "dist"  -Recurse -Force }
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

Write-Host "Gerando executavel..."

& venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name $exeName `
    --icon="icon/logo.ico" `
    --add-data "icon/logo.ico;icon" `
    --collect-all selenium `
    --collect-all PySide6 `
    --hidden-import dotenv `
    --distpath "dist" `
    --workpath "build" `
    "desktop.py"

if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o executavel.' }

$exePath = "dist\$exeName.exe"
if (-not (Test-Path $exePath)) { throw "Executavel nao encontrado: $exePath" }

Write-Host ""
Write-Host "======================================"
Write-Host " Build concluido com sucesso"
Write-Host " $exePath"
Write-Host "======================================"

if ($ExecutableOnly) { exit 0 }
