@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ============================================================
::  TENEBRIO NODE - Desinstalar servicio y restaurar sistema
::  Revierte todo lo que hizo install_service.bat
::  Ejecutar como administrador
:: ============================================================

set "SERVICE_NAME=TenebrioNode"

title Tenebrio Node - Desinstalar servicio

echo.
echo ============================================================
echo   TENEBRIO NODE - Desinstalando servicio
echo ============================================================

:: ---- [1/6] Admin ----
echo.
echo [1/6] Verificando permisos de administrador...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Requiere administrador.
    echo         Clic derecho ^> Ejecutar como administrador.
    pause & exit /b 1
)
echo       OK

:: ---- [2/6] Detener y eliminar servicio ----
echo.
echo [2/6] Deteniendo y eliminando servicio "!SERVICE_NAME!"...
where nssm >nul 2>&1
if %errorlevel% equ 0 (
    nssm status !SERVICE_NAME! >nul 2>&1
    if %errorlevel% equ 0 (
        nssm stop !SERVICE_NAME! >nul 2>&1
        timeout /t 3 /nobreak >nul
        nssm remove !SERVICE_NAME! confirm >nul 2>&1
        timeout /t 2 /nobreak >nul
        echo       Servicio eliminado.
    ) else (
        echo       El servicio no estaba instalado.
    )
) else (
    echo [AVISO] NSSM no encontrado. Omitiendo eliminacion de servicio.
)

:: ---- [3/6] Liberar puerto 5000 ----
echo.
echo [3/6] Liberando puerto 5000...
powershell -Command "Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo       OK

:: ---- [4/6] Cerrar Chrome kiosko ----
echo.
echo [4/6] Cerrando Chrome en modo kiosko...
powershell -Command "Get-WmiObject Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -match 'kiosk|localhost:5000' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo       OK

:: ---- [5/6] Eliminar kiosko del inicio de sesion ----
echo.
echo [5/6] Eliminando kiosko del inicio de sesion...
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TenebrioKiosk.bat" >nul 2>&1
echo       OK

:: ---- [6/6] Restaurar barra de tareas ----
echo.
echo [6/6] Restaurando barra de tareas...
powershell -Command "$p = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3'; $v = (Get-ItemProperty -Path $p).Settings; $v[8] = 2; Set-ItemProperty -Path $p -Name Settings -Value $v" >nul 2>&1
powershell -Command "Stop-Process -Name explorer -Force" >nul 2>&1
timeout /t 3 /nobreak >nul
echo       OK

echo.
echo ============================================================
echo   DESINSTALACION COMPLETADA
echo ============================================================
echo   Servicio:   Eliminado
echo   Puerto 5000: Liberado
echo   Kiosko:     Cerrado y eliminado del inicio
echo   Barra:      Restaurada
echo ============================================================
pause
exit /b 0
