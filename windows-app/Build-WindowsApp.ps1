# Build a Windows onedir app under windows-app\dist\DACS-DD1348-Baseline\
# Requires: Python 3.10+ on PATH, Google Chrome installed (CAC uses system Chrome).

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
Set-Location $here

Write-Host "== Syncing latest sources from repo =="
& (Join-Path $here 'Sync-From-Repo.ps1')

$venvPython = Join-Path $here '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
  Write-Host "== Creating windows-app .venv =="
  python -m venv (Join-Path $here '.venv')
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -r (Join-Path $here 'app\requirements.txt')
  & $venvPython -m pip install pyinstaller
} else {
  & $venvPython -m pip install -r (Join-Path $here 'app\requirements.txt') | Out-Null
  & $venvPython -m pip install pyinstaller | Out-Null
}

$distName = 'DACS-DD1348-Baseline'
$workDir = Join-Path $here 'build'
$distDir = Join-Path $here 'dist'
$outDir = Join-Path $distDir $distName

Write-Host "== Running PyInstaller (onedir) =="
if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
if (Test-Path $workDir) { Remove-Item -Recurse -Force $workDir }

$specArgs = @(
  '-m', 'PyInstaller',
  '--noconfirm',
  '--clean',
  '--onedir',
  '--windowed',
  '--name', $distName,
  '--paths', (Join-Path $here 'app'),
  '--distpath', $distDir,
  '--workpath', $workDir,
  '--specpath', $here,
  '--collect-all', 'playwright',
  '--collect-all', 'openpyxl',
  '--hidden-import', 'yaml',
  '--hidden-import', 'dacs_baseline',
  '--hidden-import', 'dacs_baseline.app',
  '--hidden-import', 'dacs_baseline.cli',
  (Join-Path $here 'app\launcher.py')
)

& $venvPython @specArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit $LASTEXITCODE" }

Write-Host "== Copying sidecar folders next to the exe =="
foreach ($folder in @('input', 'reports', 'user-data')) {
  $src = Join-Path $here "app\$folder"
  $dst = Join-Path $outDir $folder
  if (Test-Path $src) {
    Copy-Item -Recurse -Force $src $dst
  } else {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
  }
}
Copy-Item -Force (Join-Path $here 'app\config.example.yaml') $outDir
Copy-Item -Force (Join-Path $here 'app\requirements.txt') $outDir
Copy-Item -Force (Join-Path $here 'README.md') (Join-Path $outDir 'README-WindowsApp.md')

# Console helper bat beside the exe (shows errors if GUI fails to start)
$helper = @'
@echo off
cd /d "%~dp0"
start "" "%~dp0DACS-DD1348-Baseline.exe"
'@
Set-Content -Path (Join-Path $outDir 'Start DACS DD1348 Baseline.bat') -Value $helper -Encoding ASCII

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $outDir"
Write-Host ""
Write-Host "Double-click: DACS-DD1348-Baseline.exe"
Write-Host "Or zip the whole folder and copy to the VM."
Write-Host "Requires Google Chrome installed for CAC login."
