@echo off
setlocal
cd /d "%~dp0"

set "PIDFILE=%CD%\.osint-server.pid"
set "OUTLOG=%CD%\.osint-server.out.log"
set "ERRLOG=%CD%\.osint-server.err.log"
set "PY=%CD%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo OSINT Local: virtual environment not found.
  echo Run installation first.
  pause
  exit /b 1
)

if exist "%PIDFILE%" (
  set /p OLD_PID=<"%PIDFILE%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:OLD_PID) -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -match 'osint_local\.cli serve') { exit 0 } else { exit 1 }" >nul 2>&1
  if not errorlevel 1 (
    start "" "http://127.0.0.1:8080"
    exit /b 0
  )
  del /q "%PIDFILE%" >nul 2>&1
)

set "OSINT_PY=%PY%"
set "OSINT_DIR=%CD%"
set "OSINT_OUT=%OUTLOG%"
set "OSINT_ERR=%ERRLOG%"

for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath $env:OSINT_PY -ArgumentList '-m','osint_local.cli','serve','--no-open' -WorkingDirectory $env:OSINT_DIR -WindowStyle Hidden -RedirectStandardOutput $env:OSINT_OUT -RedirectStandardError $env:OSINT_ERR -PassThru; $p.Id"') do set "OSINT_PID=%%P"

if not defined OSINT_PID (
  echo OSINT Local failed to start.
  pause
  exit /b 1
)

> "%PIDFILE%" echo %OSINT_PID%
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8080"
exit /b 0
