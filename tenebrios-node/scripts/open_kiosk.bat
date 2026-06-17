@echo off
:: Abre Chrome en modo kiosko apuntando al servidor Node.
:: Este archivo se copia a la carpeta Startup al instalar el servicio.

set "APP_URL=http://localhost:5000"
set "WAIT_SECONDS=15"

timeout /t %WAIT_SECONDS% /nobreak >nul

set "BROWSER="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "BROWSER=C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "BROWSER=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

if not defined BROWSER exit /b 1

powershell -Command "$p = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3'; $v = (Get-ItemProperty -Path $p).Settings; $v[8] = 3; Set-ItemProperty -Path $p -Name Settings -Value $v" >nul 2>&1
powershell -Command "Stop-Process -Name explorer -Force" >nul 2>&1
timeout /t 3 /nobreak >nul

start "" "%BROWSER%" --kiosk --new-window --no-first-run --no-default-browser-check --no-restore --disable-translate --disable-extensions "%APP_URL%"
