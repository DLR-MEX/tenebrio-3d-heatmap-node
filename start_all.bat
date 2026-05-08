@echo off
REM =====================================================================
REM  start_all.bat - Arranca dashboard 3D + sidecar IA Python
REM  ------------------------------------------------------------------
REM   - tenebrios-node  -> Express + Babylon.js  (puerto 5000, visible)
REM   - ai-predictor    -> FastAPI + GRU + agente IA (puerto 8001, loopback)
REM
REM  Abre http://localhost:5000 — las rutas /api/predictor/* las proxea
REM  Express al sidecar. Cada servicio tiene su propio .env.
REM
REM  Cierre: cierra cualquiera de las dos ventanas para detener ese
REM  servicio. Tambien Ctrl+C en cualquiera funciona.
REM =====================================================================

setlocal
cd /d "%~dp0"

set "ROOT=%~dp0"
set "NODE_DIR=%ROOT%tenebrios-node"
set "AI_DIR=%ROOT%ai-predictor"
set "SIDECAR_PORT=8001"

REM --- Verificar que ambos .env existan -------------------------------
if not exist "%NODE_DIR%\.env" (
    echo [ERROR] Falta %NODE_DIR%\.env
    echo         Copia tenebrios-node\.env.example a tenebrios-node\.env
    pause
    exit /b 1
)
if not exist "%AI_DIR%\.env" (
    echo [ERROR] Falta %AI_DIR%\.env
    echo         Copia ai-predictor\.env.example a ai-predictor\.env y
    echo         configura UBIDOTS_TOKEN, OLLAMA_API_KEY, TELEGRAM_BOT_TOKEN.
    pause
    exit /b 1
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
echo   - Vista 3D (Danny) ... botones del header
echo   - Vista IA + chat .... boton IA del header, o tecla V
echo   Sidecar (debug) ...... http://127.0.0.1:%SIDECAR_PORT%/healthz
echo  -------------------------------------------------------------------
echo   Python venv: %PY%
echo  -------------------------------------------------------------------
echo   Cierra esta ventana o pulsa Ctrl+C para detener Express.
echo   El sidecar abre en otra ventana — cierrala para detener Python.
echo  ===================================================================
echo.

REM --- Sidecar IA en otra ventana (loopback only) ---------------------
REM APP_HOST=127.0.0.1 forzado: aunque el .env diga 0.0.0.0, el sidecar
REM solo debe ser accesible desde la misma maquina (Express lo proxea).
start "AI Predictor (puerto %SIDECAR_PORT%)" cmd /k ^
    "cd /d "%AI_DIR%" ^&^& set APP_HOST=127.0.0.1^&^& set APP_PORT=%SIDECAR_PORT%^&^& "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %SIDECAR_PORT%"

REM --- Esperar a que el sidecar este listo ----------------------------
REM TensorFlow tarda ~10-20s cargando los modelos. Hacemos un health
REM check en lugar de un timeout fijo.
echo  Esperando a que el predictor cargue modelos GRU (puede tardar 15-30s)...
set /a tries=0
:wait_sidecar
set /a tries+=1
if %tries% GTR 60 (
    echo  [WARN] Sidecar no respondio en 60s. Revisa la ventana 'AI Predictor'.
    echo         Continuando — Express arrancara igual y reintentara.
    goto start_express
)
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%SIDECAR_PORT%/healthz' -TimeoutSec 1).StatusCode } catch { 0 }" | findstr /C:"200" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_sidecar
)
echo  Sidecar listo.

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
