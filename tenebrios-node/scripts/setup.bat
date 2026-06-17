@echo off
REM Script de instalación para TENEBRIOS 3D (Windows)
REM Verifica Node.js e instala dependencias

echo.
echo ====================================
echo   TENEBRIOS 3D - Setup (Windows)
echo ====================================
echo.

REM Verificar si Node.js está instalado
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Node.js no está instalado o no está en PATH
    echo.
    echo Por favor instala Node.js desde: https://nodejs.org/
    echo Requiere version: 20.0.0 o superior
    echo.
    pause
    exit /b 1
)

REM Obtener versiones
for /f "tokens=*" %%i in ('node --version') do set NODE_VERSION=%%i
for /f "tokens=*" %%i in ('npm --version') do set NPM_VERSION=%%i

echo [✓] Node.js encontrado: %NODE_VERSION%
echo [✓] npm encontrado: %NPM_VERSION%
echo.

REM Instalar dependencias
echo Instalando dependencias npm...
call npm install

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Error durante la instalación de npm
    pause
    exit /b 1
)

echo.
echo [✓] Instalación completada exitosamente
echo.
echo Próximos pasos:
echo   1. Crear archivo .env desde .env.example (si no existe)
echo   2. Ejecutar: npm start
echo   3. O para desarrollo: npm run dev
echo.
pause
