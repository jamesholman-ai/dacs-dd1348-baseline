@echo off
REM Double-click launcher for DACS DD1348 Baseline Scanner.
REM First run: creates .venv, installs deps, opens setup + GUI.

cd /d "%~dp0"
setlocal

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.10+ and retry.
    pause
    exit /b 1
  )
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install requirements
    pause
    exit /b 1
  )
  echo.
  echo Playwright will use your installed Google Chrome for CAC.
  echo.
)

".venv\Scripts\python.exe" -m dacs_baseline
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Exited with code %EXITCODE%
  pause
)
exit /b %EXITCODE%
