@echo off
setlocal

cd /d "%~dp0"

if not exist ".env" (
  echo [ERROR] No se encontro .env
  echo         Copia .env.example a .env y rellena las credenciales de Ubidots.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if /i "%%A"=="APP_HOST" set "APP_HOST=%%B"
  if /i "%%A"=="APP_PORT" set "APP_PORT=%%B"
)
if not defined APP_HOST set "APP_HOST=127.0.0.1"
if not defined APP_PORT set "APP_PORT=8000"

echo.
echo  Tenebris AI Sentinel - dashboard
echo  --------------------------------
echo  http://%APP_HOST%:%APP_PORT%
echo.
echo  Ctrl+C para detener
echo.

start "" /b cmd /c "timeout /t 12 /nobreak >nul && start "" http://%APP_HOST%:%APP_PORT%"

"%PY%" -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT%

endlocal
