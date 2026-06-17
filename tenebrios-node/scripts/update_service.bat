@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ============================================================
::  TENEBRIO NODE - Actualizar dependencias y reiniciar servicio
::  Ejecutar como administrador
:: ============================================================

set "SERVICE_NAME=TenebrioNode"
set "PROJECT_DIR=%~dp0.."

if "!PROJECT_DIR:~-1!"=="\" set "PROJECT_DIR=!PROJECT_DIR:~0,-1!"

title Tenebrio Node - Actualizar servicio

echo.
echo ============================================================
echo   TENEBRIO NODE - Actualizando servicio
echo ============================================================

:: ---- [1/4] Admin ----
echo.
echo [1/4] Verificando permisos de administrador...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Requiere administrador.
    echo         Clic derecho ^> Ejecutar como administrador.
    pause & exit /b 1
)
echo       OK

:: ---- [2/4] NSSM y servicio ----
echo.
echo [2/4] Verificando servicio...
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] NSSM no encontrado en PATH.
    pause & exit /b 1
)
nssm status !SERVICE_NAME! >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] El servicio "!SERVICE_NAME!" no esta instalado.
    echo         Ejecuta install_service.bat primero.
    pause & exit /b 1
)
echo       OK

:: ---- [3/4] Detener, instalar deps, reiniciar ----
echo.
echo [3/4] Deteniendo servicio para actualizar...
nssm stop !SERVICE_NAME! >nul 2>&1
timeout /t 3 /nobreak >nul
echo       OK

echo.
echo       Instalando dependencias npm en: !PROJECT_DIR!
cd /d "!PROJECT_DIR!"
call npm install
if %errorlevel% neq 0 (
    echo [ERROR] npm install fallo. El servicio no se reiniciara.
    pause & exit /b 1
)

:: ---- [4/4] Reiniciar ----
echo.
echo [4/4] Reiniciando servicio...
nssm start !SERVICE_NAME!
if %errorlevel% neq 0 (
    echo [ERROR] No se pudo reiniciar el servicio.
    echo         Ejecuta: nssm status !SERVICE_NAME!
    pause & exit /b 1
)

echo.
echo ============================================================
echo   ACTUALIZACION COMPLETADA
echo ============================================================
echo   Servicio !SERVICE_NAME! reiniciado correctamente.
echo ============================================================
pause
exit /b 0
