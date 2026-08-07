@echo off
REM Launch the packaged Windows app if built; otherwise run from the local copy with Python.
cd /d "%~dp0"

if exist "dist\DACS-DD1348-Baseline\DACS-DD1348-Baseline.exe" (
  start "" "dist\DACS-DD1348-Baseline\DACS-DD1348-Baseline.exe"
  exit /b 0
)

echo Packaged exe not found. Running from source copy in app\ ...
echo (Run Build-WindowsApp.ps1 once to create the .exe package.)
echo.

if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.10+ and retry.
    pause
    exit /b 1
  )
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r app\requirements.txt
)

cd app
"..\.venv\Scripts\python.exe" launcher.py
if errorlevel 1 pause
exit /b %ERRORLEVEL%
