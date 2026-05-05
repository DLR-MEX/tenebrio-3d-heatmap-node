@echo off
REM =====================================================================
REM  start_all.bat - Arranca el dashboard 3D de Danny + sidecar IA Python
REM  ------------------------------------------------------------------
REM   - tenebrios-node  -> Express + Babylon.js  (puerto 5000, visible)
REM   - ai-predictor    -> FastAPI + GRU models  (puerto 8000, oculto a 127.0.0.1)
REM
REM  El usuario solo abre http://localhost:5000 ; las rutas /api/predictor/*
REM  son proxeadas por Express hacia el sidecar.
REM
REM  Cada servicio mantiene su propio .env (cada uno con sus credenciales).
REM =====================================================================

setlocal
cd /d "%~dp0"

set "ROOT=%~dp0"
set "NODE_DIR=%ROOT%tenebrios-node"
set "AI_DIR=%ROOT%ai-predictor"

REM --- Verificar que ambos .env existan -------------------------------
if not exist "%NODE_DIR%\.env" (
    echo [ERROR] Falta %NODE_DIR%\.env
    echo         Copia tenebrios-node\.env.example a tenebrios-node\.env
    pause
    exit /b 1
)
if not exist "%AI_DIR%\.env" (
    echo [ERROR] Falta %AI_DIR%\.env
    echo         Copia ai-predictor\.env.example a ai-predictor\.env
    pause
    exit /b 1
)

REM --- Resolver Python (preferir venv local en ai-predictor) ----------
if exist "%AI_DIR%\.venv\Scripts\python.exe" (
    set "PY=%AI_DIR%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo.
echo  ===================================================================
echo   Tenebrio 3D + AI Sentinel
echo  ===================================================================
echo   3D Dashboard ........ http://localhost:5000
echo   AI Predictor (proxy)  http://localhost:5000  (botón IA en el header)
echo   AI direct (debug) ... http://127.0.0.1:8000  (no expuesto fuera)
echo  -------------------------------------------------------------------
echo   Cierra esta ventana o pulsa Ctrl+C para detener AMBOS procesos.
echo  ===================================================================
echo.

REM --- Forzar al sidecar a escuchar SOLO en loopback ------------------
REM Aunque el .env diga 0.0.0.0, exportamos APP_HOST=127.0.0.1 para que
REM el predictor no quede expuesto a la red local. El proxy Express si
REM puede atarse a 0.0.0.0 (es el unico que el usuario debe ver).
set "APP_HOST=127.0.0.1"
set "APP_PORT=8000"

REM --- Levantar sidecar IA en otra ventana ----------------------------
start "AI Predictor" cmd /k "cd /d "%AI_DIR%" && set APP_HOST=127.0.0.1&& set APP_PORT=8000&& "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

REM --- Pequeña espera para que FastAPI cargue los modelos -------------
echo  Esperando a que el predictor cargue modelos...
timeout /t 6 /nobreak >nul

REM --- Levantar server Node en esta ventana (foreground) --------------
cd /d "%NODE_DIR%"
call npm start

endlocal
