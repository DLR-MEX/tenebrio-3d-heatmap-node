@echo off
REM =====================================================================
REM  start_all.bat - Arranca dashboard 3D + sidecar IA Python
REM  ------------------------------------------------------------------
REM   - tenebrios-node  -> Express + Babylon.js  (puerto 5000, visible)
REM   - ai-predictor    -> FastAPI + GRU + agente IA (puerto 8001, loopback)
REM
REM  Abre http://localhost:5000. Las rutas /api/predictor/* las proxea
REM  Express al sidecar. Cada servicio tiene su propio .env.
REM
REM  Cierre: cierra cualquiera de las dos ventanas (o Ctrl+C en ellas).
REM =====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%~dp0"
set "NODE_DIR=%ROOT%tenebrios-node"
set "AI_DIR=%ROOT%ai-predictor"
set "SIDECAR_PORT=8001"

REM --- Verificar .env del sidecar (REQUERIDO; Express tiene defaults) -
if not exist "%AI_DIR%\.env" (
    echo [ERROR] Falta %AI_DIR%\.env
    echo         Copia ai-predictor\.env.example a ai-predictor\.env y
    echo         configura UBIDOTS_TOKEN, OLLAMA_API_KEY, TELEGRAM_BOT_TOKEN.
    pause
    exit /b 1
)
if not exist "%NODE_DIR%\.env" (
    echo [INFO] No hay tenebrios-node\.env — Express usara defaults del config.js.
    echo        Para personalizar, copia tenebrios-node\.env.example a .env.
    echo.
)

REM --- Resolver Python (orden de preferencia) ------------------------
REM   1. venv local en ai-predictor\.venv
REM   2. venv "corto" en C:\tnvenv (workaround Windows long-path para TensorFlow)
REM   3. python en PATH
if exist "%AI_DIR%\.venv\Scripts\python.exe" (
    set "PY=%AI_DIR%\.venv\Scripts\python.exe"
) else if exist "C:\tnvenv\Scripts\python.exe" (
    set "PY=C:\tnvenv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo.
echo  ===================================================================
echo   Tenebrio 3D + AI Sentinel
echo  ===================================================================
echo   Dashboard ............ http://localhost:5000
echo   Sidecar (debug) ...... http://127.0.0.1:%SIDECAR_PORT%/healthz
echo  -------------------------------------------------------------------
echo   Python venv: !PY!
echo  -------------------------------------------------------------------
echo   Cierra cualquier ventana (o Ctrl+C) para detener su servicio.
echo  ===================================================================
echo.

REM --- Sidecar IA en otra ventana (loopback only) ---------------------
REM APP_HOST/PORT exportados ANTES del start asi se pasan al hijo;
REM la ventana hija hereda el entorno actual de cmd.
set "APP_HOST=127.0.0.1"
set "APP_PORT=%SIDECAR_PORT%"
start "AI Predictor (puerto %SIDECAR_PORT%)" /D "%AI_DIR%" cmd /k "!PY! -m uvicorn app.main:app --host 127.0.0.1 --port %SIDECAR_PORT%"

REM --- Esperar a que el sidecar este listo ----------------------------
REM TensorFlow tarda 10-25s cargando los modelos. Loop con curl (bundled
REM en Windows 10+). Si curl no existe, fallback a timeout fijo de 25s.
where curl >nul 2>&1
if %errorlevel% NEQ 0 (
    echo  Esperando 25s a que carguen los modelos GRU...
    timeout /t 25 /nobreak >nul
    goto start_express
)

echo  Esperando a que el predictor responda /healthz (max 60s)...
set /a tries=0
:wait_sidecar
set /a tries+=1
if !tries! GTR 60 (
    echo  [WARN] Sidecar no respondio en 60s. Revisa la ventana "AI Predictor".
    echo         Continuando — Express arrancara igual y reintentara.
    goto start_express
)
curl -s -f -o NUL --max-time 1 "http://127.0.0.1:%SIDECAR_PORT%/healthz" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_sidecar
)
echo  Sidecar listo (intento !tries!).

:start_express
REM --- Express (foreground en esta ventana) ---------------------------
REM AI_PREDICTOR_BASE le dice al proxy donde encontrar al sidecar.
cd /d "%NODE_DIR%"
set "AI_PREDICTOR_BASE=http://127.0.0.1:%SIDECAR_PORT%"
echo.
echo  Arrancando Express en http://localhost:5000 ...
echo.
call npm start

endlocal
