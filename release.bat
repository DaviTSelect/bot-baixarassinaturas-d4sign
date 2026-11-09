@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  Release - D4Sign Central Bolsas
echo ============================================

if exist "venv\Scripts\python.exe" (
    set PY=venv\Scripts\python.exe
    set PIP=venv\Scripts\pip.exe
    set PYINST=venv\Scripts\pyinstaller.exe
) else (
    set PY=python
    set PIP=pip
    set PYINST=pyinstaller
)

for /f "usebackq delims=" %%v in (`%PY% -c "from d4sign.version import VERSION; print(VERSION)"`) do set VERSION=%%v
if "%VERSION%"=="" (
    echo ERRO: nao foi possivel ler VERSION de d4sign\version.py
    pause & exit /b 1
)
set TAG=v%VERSION%
echo Versao: %TAG%
echo.

:: git reside na pasta pai
pushd ..
git fetch --tags -q 2>nul
git rev-parse "%TAG%" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    popd
    echo ERRO: tag %TAG% ja existe.
    echo Incremente VERSION em d4sign\version.py antes de fazer release.
    pause & exit /b 1
)
popd

echo [1/5] Instalando dependencias de build...
%PIP% install -r requirements-build.txt -q
if %ERRORLEVEL% neq 0 ( echo ERRO ao instalar dependencias & pause & exit /b 1 )

echo [2/5] Executando testes...
%PY% -m pytest test -q 2>nul
if %ERRORLEVEL% neq 0 ( echo ERRO nos testes & pause & exit /b 1 )

echo [3/5] Compilando executavel...
if exist dist rmdir /s /q dist
%PYINST% D4Sign.spec --noconfirm
if %ERRORLEVEL% neq 0 ( echo ERRO no PyInstaller & pause & exit /b 1 )
if not exist "dist\D4Sign.exe" (
    echo ERRO: dist\D4Sign.exe nao encontrado
    pause & exit /b 1
)

echo [4/5] Calculando SHA-256...
for /f "usebackq delims=" %%h in (`powershell -NoProfile -Command "(Get-FileHash 'dist\D4Sign.exe' -Algorithm SHA256).Hash.ToLower()"`) do set SHA256=%%h
echo %SHA256%  D4Sign.exe > dist\D4Sign.exe.sha256
echo SHA-256: %SHA256%

echo [5/5] Publicando release %TAG% no GitHub...
pushd ..
git tag %TAG%
git push origin %TAG%
if %ERRORLEVEL% neq 0 (
    git tag -d %TAG% >nul 2>&1
    popd
    echo ERRO ao enviar tag para o GitHub
    pause & exit /b 1
)
popd

set NOTES_FILE=%TEMP%\release_notes_%VERSION%.md
(
    echo ## Instalacao
    echo.
    echo 1. Baixe D4Sign.exe
    echo 2. Coloque na pasta desejada
    echo 3. Execute D4Sign.exe
    echo.
    echo **SHA-256:** %SHA256%
) > "%NOTES_FILE%"

gh release create %TAG% ^
    "dist\D4Sign.exe" ^
    "dist\D4Sign.exe.sha256" ^
    --title "D4Sign Central Bolsas %TAG%" ^
    --notes-file "%NOTES_FILE%" ^
    --repo DaviTSelect/bot-baixarassinaturas-d4sign

if %ERRORLEVEL% neq 0 (
    echo ERRO ao criar release no GitHub
    del "%NOTES_FILE%" >nul 2>&1
    pause & exit /b 1
)
del "%NOTES_FILE%" >nul 2>&1

echo.
echo ============================================
echo  Release %TAG% publicada com sucesso!
echo  https://github.com/DaviTSelect/bot-baixarassinaturas-d4sign/releases/tag/%TAG%
echo ============================================
pause
