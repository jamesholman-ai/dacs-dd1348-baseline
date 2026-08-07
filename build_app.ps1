# Optional: build a clickable folder under dist\DACS-DD1348-Baseline\
# The recommended day-to-day launcher is still Start-DACS-Baseline.bat
# (venv + system Chrome for CAC). This packages the GUI entry point.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

.\.venv\Scripts\python.exe -m pip install pyinstaller

$distRoot = Join-Path $PSScriptRoot 'dist\DACS-DD1348-Baseline'
New-Item -ItemType Directory -Force -Path $distRoot | Out-Null

# Copy project payload the exe will sit beside
$payload = @(
  'dacs_baseline',
  'input',
  'reports',
  'requirements.txt',
  'config.example.yaml',
  'Start-DACS-Baseline.bat',
  'Run-Scan.ps1',
  'README.md'
)
foreach ($item in $payload) {
  $src = Join-Path $PSScriptRoot $item
  if (Test-Path $src) {
    Copy-Item -Recurse -Force $src (Join-Path $distRoot (Split-Path $item -Leaf))
  }
}

# Ensure empty dirs exist for first-run customization
New-Item -ItemType Directory -Force -Path (Join-Path $distRoot 'reports\dd1348-irrd') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $distRoot 'user-data') | Out-Null

# Write a bootstrap that uses local .venv next to the package
$launcher = @'
@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating .venv and installing packages...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" -m dacs_baseline
if errorlevel 1 pause
'@
Set-Content -Path (Join-Path $distRoot 'DACS-DD1348-Baseline.bat') -Value $launcher -Encoding ASCII

Write-Host ""
Write-Host "Packaged to: $distRoot"
Write-Host "Zip that folder and copy to the VM. Double-click DACS-DD1348-Baseline.bat"
Write-Host "(or Start-DACS-Baseline.bat). First click runs setup for paths."
