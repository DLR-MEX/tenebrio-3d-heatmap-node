@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ============================================================
::  TENEBRIO NODE - Eliminar servicio ANTERIOR (Python/Flask)
::  Limpia el servicio "TenebrioHeatmap" creado por los scripts
::  viejos de la version Python del proyecto.
::  Ejecutar como administrador
:: ============================================================

set "OLD_SERVICE_NAME=TenebrioHeatmap"

title Tenebrio - Eliminar servicio anterior (Python)

echo.
echo ============================================================
echo   Eliminando servicio anterior: !OLD_SERVICE_NAME!
echo ============================================================

:: ---- [1/5] Admin ----
echo.
echo [1/5] Verificando permisos de administrador...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Requiere administrador.
    echo         Clic derecho ^> Ejecutar como administrador.
    pause & exit /b 1
)
echo       OK

:: ---- [2/5] Detener y eliminar servicio antiguo ----
echo.
echo [2/5] Deteniendo y eliminando servicio "!OLD_SERVICE_NAME!"...
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] NSSM no encontrado en PATH. Omitiendo.
    goto :KILL_PYTHON
)
nssm status !OLD_SERVICE_NAME! >nul 2>&1
if %errorlevel% neq 0 (
    echo       El servicio no estaba instalado.
    goto :KILL_PYTHON
)
nssm stop !OLD_SERVICE_NAME! >nul 2>&1
timeout /t 3 /nobreak >nul
for /f "tokens=3" %%p in ('sc queryex !OLD_SERVICE_NAME! ^| findstr PID') do (
    if %%p neq 0 taskkill /PID %%p /T /F >nul 2>&1
)
nssm remove !OLD_SERVICE_NAME! confirm >nul 2>&1
timeout /t 2 /nobreak >nul
echo       Servicio eliminado.

:: ---- [3/5] Matar procesos Python residuales y liberar puerto 5000 ----
:KILL_PYTHON
echo.
echo [3/5] Cerrando procesos Python y liberando puerto 5000...
powershell -Command "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'main\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -Command "Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo       OK

:: ---- [4/5] Limpiar kiosko antiguo del inicio de sesion ----
echo.
echo [4/5] Limpiando entradas antiguas del inicio de sesion...
schtasks /delete /tn "TenebrioKiosk" /f >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TenebrioKiosk.bat" >nul 2>&1
powershell -Command "
$paths = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\Run');
foreach ($p in \$paths) {
    Get-ItemProperty -Path \$p -ErrorAction SilentlyContinue | ForEach-Object {
        \$_.PSObject.Properties | Where-Object { \$_.Value -match 'localhost:5000|kiosk' } | ForEach-Object {
            Remove-ItemProperty -Path \$p -Name \$_.Name -Force -ErrorAction SilentlyContinue
        }
    }
}" >nul 2>&1
echo       OK

:: ---- [5/5] Limpiar politicas de Edge que bloquearon el viejo setup ----
echo.
echo [5/5] Restaurando politicas de Edge...
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge" /v StartupBoostEnabled /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge" /v BackgroundModeEnabled /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge" /v AllowPrelaunch /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Edge" /v RestoreOnStartup /f >nul 2>&1
echo       OK

echo.
echo ============================================================
echo   LIMPIEZA COMPLETADA
echo ============================================================
echo   Servicio !OLD_SERVICE_NAME!: Eliminado
echo   Python / Puerto 5000:        Liberados
echo   Inicio de sesion antiguo:    Limpiado
echo   Politicas Edge:              Restauradas
echo ============================================================
pause
exit /b 0
