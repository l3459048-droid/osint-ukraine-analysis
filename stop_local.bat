@echo off
setlocal
cd /d "%~dp0"

set "PIDFILE=%CD%\.osint-server.pid"
set "STOPFILE=%CD%\.osint-stop"

> "%STOPFILE%" echo stop

if not exist "%PIDFILE%" (
  timeout /t 1 /nobreak >nul
  del /q "%STOPFILE%" >nul 2>&1
  exit /b 0
)

set /p OSINT_PID=<"%PIDFILE%"

for /l %%I in (1,1,10) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-Process -Id %OSINT_PID% -ErrorAction SilentlyContinue; if ($p) { exit 1 } else { exit 0 }" >nul 2>&1
  if not errorlevel 1 goto stopped
  timeout /t 1 /nobreak >nul
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%OSINT_PID%' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -match 'osint_local\.cli serve') { Stop-Process -Id %OSINT_PID% -Force }" >nul 2>&1

:stopped
del /q "%PIDFILE%" >nul 2>&1
del /q "%STOPFILE%" >nul 2>&1
exit /b 0
