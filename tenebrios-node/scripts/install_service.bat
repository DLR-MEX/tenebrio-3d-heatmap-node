@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ============================================================
::  TENEBRIO NODE - Instalar servicio Windows + kiosko
::  Requiere: NSSM en PATH, Node.js v20+, Chrome instalado
::  Ejecutar como administrador
:: ============================================================

set "SERVICE_NAME=TenebrioNode"
set "PROJECT_DIR=%~dp0.."
set "LOGS_DIR=%PROJECT_DIR%\logs"
set "APP_URL=http://localhost:5000"
set "WAIT_SECONDS=10"

if "!PROJECT_DIR:~-1!"=="\" set "PROJECT_DIR=!PROJECT_DIR:~0,-1!"
if "!LOGS_DIR:~-1!"=="\" set "LOGS_DIR=!LOGS_DIR:~0,-1!"

title Tenebrio Node - Instalador de servicio

echo.
echo ============================================================
echo   TENEBRIO NODE - Instalando servicio
echo ============================================================

:: ---- [1/7] Admin ----
echo.
echo [1/7] Verificando permisos de administrador...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Requiere administrador.
    echo         Clic derecho ^> Ejecutar como administrador.
    pause & exit /b 1
)
echo       OK

:: ---- [2/7] NSSM ----
echo.
echo [2/7] Verificando NSSM...
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] NSSM no encontrado en PATH.
    echo         Descarga nssm.exe desde https://nssm.cc/download
    echo         y coloca el ejecutable en C:\Windows\System32\
    pause & exit /b 1
)
echo       OK

:: ---- [3/7] Node.js ----
echo.
echo [3/7] Verificando Node.js...
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js no encontrado. Instala desde https://nodejs.org/ ^(v20+^)
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('where node 2^>nul') do (
    if not defined NODE_EXE set "NODE_EXE=%%i"
)
for /f "tokens=*" %%i in ('node --version 2^>nul') do set "NODE_VER=%%i"
echo       OK - Node.js !NODE_VER! en: !NODE_EXE!

:: ---- [4/7] Logs ----
echo.
echo [4/7] Preparando carpeta de logs...
if not exist "!LOGS_DIR!" (
    mkdir "!LOGS_DIR!"
    echo       Carpeta creada.
) else (
    echo       Ya existe.
)

:: ---- [5/7] Instalar servicio ----
echo.
echo [5/7] Instalando servicio "!SERVICE_NAME!"...

nssm status !SERVICE_NAME! >nul 2>&1
if %errorlevel% equ 0 (
    echo       Deteniendo servicio existente...
    nssm stop !SERVICE_NAME! >nul 2>&1
    timeout /t 3 /nobreak >nul
    nssm remove !SERVICE_NAME! confirm >nul 2>&1
    timeout /t 2 /nobreak >nul
)

powershell -Command "Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

nssm install !SERVICE_NAME! "!NODE_EXE!" "src/index.js"
if %errorlevel% neq 0 (
    echo [ERROR] No se pudo instalar el servicio.
    pause & exit /b 1
)

nssm set !SERVICE_NAME! AppDirectory "!PROJECT_DIR!"
nssm set !SERVICE_NAME! AppStdout "!LOGS_DIR!\service.log"
nssm set !SERVICE_NAME! AppStderr "!LOGS_DIR!\service.log"
nssm set !SERVICE_NAME! AppStdoutCreationDisposition 2
nssm set !SERVICE_NAME! AppStderrCreationDisposition 2
nssm set !SERVICE_NAME! AppRotateFiles 0
nssm set !SERVICE_NAME! AppRestartDelay 5000
nssm set !SERVICE_NAME! AppExit Default Restart
nssm set !SERVICE_NAME! DisplayName "Tenebrio 3D Heatmap (Node)"
nssm set !SERVICE_NAME! Description "Visualizacion 3D temperatura cuarto de cria de tenebrios"
nssm set !SERVICE_NAME! Start SERVICE_AUTO_START
echo       OK

:: ---- [6/7] Iniciar servicio ----
echo.
echo [6/7] Iniciando servicio...
nssm start !SERVICE_NAME!
if %errorlevel% neq 0 (
    echo [ERROR] No se pudo iniciar. Revisa: !LOGS_DIR!\service.log
    pause & exit /b 1
)
echo       OK - Servicio activo.

:: ---- [7/7] Kiosko al inicio de sesion ----
echo.
echo [7/7] Configurando kiosko al inicio de sesion...
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /Y "%~dp0open_kiosk.bat" "!STARTUP_FOLDER!\TenebrioKiosk.bat" >nul 2>&1
if %errorlevel% equ 0 (
    echo       OK - Se abrira al iniciar sesion.
) else (
    echo [AVISO] No se pudo copiar a Startup. El kiosko no se abrira automaticamente.
)

:: Abrir kiosko ahora
echo.
echo       Esperando !WAIT_SECONDS!s para que el servidor arranque...
timeout /t %WAIT_SECONDS% /nobreak >nul

set "BROWSER="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "BROWSER=C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "BROWSER=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

if defined BROWSER (
    powershell -Command "$p = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3'; $v = (Get-ItemProperty -Path $p).Settings; $v[8] = 3; Set-ItemProperty -Path $p -Name Settings -Value $v" >nul 2>&1
    powershell -Command "Stop-Process -Name explorer -Force" >nul 2>&1
    timeout /t 3 /nobreak >nul
    start "" "!BROWSER!" --kiosk --new-window --no-first-run --no-default-browser-check --no-restore --disable-translate --disable-extensions "!APP_URL!"
) else (
    echo [AVISO] Chrome no encontrado. Abre manualmente: !APP_URL!
)

echo.
echo ============================================================
echo   INSTALACION COMPLETADA
echo ============================================================
echo   Servicio:  !SERVICE_NAME! ^(arranca con Windows^)
echo   Kiosko:    Se abre al iniciar sesion
echo   URL:       !APP_URL!
echo   Logs:      !LOGS_DIR!\service.log
echo.
echo   Para desinstalar: uninstall_service.bat
echo ============================================================
pause
exit /b 0
