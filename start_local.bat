@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m osint_local.cli serve %*
) else (
  python -m osint_local.cli serve %*
)
endlocal
