# Sync copied sources from the repo root into windows-app\app\
# Does NOT modify repo-root project files — only refreshes this package copy.
# Preserves windows-app-specific launcher.py and frozen-aware app.py.

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = Split-Path $here -Parent
$dest = Join-Path $here 'app'
$launcherBackup = Join-Path $here '_keep_launcher.py'
$appPyBackup = Join-Path $here '_keep_app.py'

Copy-Item -Force (Join-Path $dest 'launcher.py') $launcherBackup
Copy-Item -Force (Join-Path $dest 'dacs_baseline\app.py') $appPyBackup

Write-Host "Syncing from: $repo"
Write-Host "Into:         $dest"

New-Item -ItemType Directory -Force -Path "$dest\input" | Out-Null
New-Item -ItemType Directory -Force -Path "$dest\reports\dd1348-irrd" | Out-Null
New-Item -ItemType Directory -Force -Path "$dest\user-data" | Out-Null

robocopy (Join-Path $repo 'dacs_baseline') (Join-Path $dest 'dacs_baseline') /E /XD __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
Copy-Item -Force (Join-Path $repo 'requirements.txt') $dest
Copy-Item -Force (Join-Path $repo 'config.example.yaml') $dest
Copy-Item -Force (Join-Path $repo 'input\identifiers-sample-10.txt') (Join-Path $dest 'input')
Copy-Item -Force (Join-Path $repo 'input\identifiers-full-462.txt') (Join-Path $dest 'input')
Copy-Item -Force (Join-Path $repo 'input\README.md') (Join-Path $dest 'input')
if (Test-Path (Join-Path $repo 'reports\dd1348-irrd\README.md')) {
  Copy-Item -Force (Join-Path $repo 'reports\dd1348-irrd\README.md') (Join-Path $dest 'reports\dd1348-irrd')
}

Copy-Item -Force $launcherBackup (Join-Path $dest 'launcher.py')
Copy-Item -Force $appPyBackup (Join-Path $dest 'dacs_baseline\app.py')
Remove-Item -Force $launcherBackup, $appPyBackup -ErrorAction SilentlyContinue

Write-Host "Sync complete (launcher.py and app.py windows-app patches preserved)."
