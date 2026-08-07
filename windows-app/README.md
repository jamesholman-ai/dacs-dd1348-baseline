# DACS DD1348 Baseline — Windows App package

This folder is a **standalone Windows packaging area**. It copies what it needs from
the repo root and does **not** modify the original project files.

## Quick start (no build)

1. Double-click **`Launch-DACS-Baseline.bat`**
2. First run creates a local `.venv`, installs packages, opens the GUI
3. Complete first-time setup (paths / EFTS URL)
4. Use system **Google Chrome** for CAC

## Build a clickable Windows app (.exe)

On a machine with Python 3.10+:

```powershell
cd windows-app
.\Build-WindowsApp.ps1
```

Output:

```
windows-app\dist\DACS-DD1348-Baseline\
  DACS-DD1348-Baseline.exe
  Start DACS DD1348 Baseline.bat
  input\
  reports\
  user-data\
  ...
```

Zip that whole folder and copy it to the gov-cloud VM. Double-click the `.exe`
(or the Start bat). Chrome must be installed on the VM for CAC.

Or create a zip:

```powershell
.\Zip-WindowsApp.ps1
```

## Refresh copied sources from the repo

```powershell
cd windows-app
.\Sync-From-Repo.ps1
```

Then rebuild if you want an updated `.exe`.

## Layout

| Path | Purpose |
|------|---------|
| `app\` | Copied Python package + sample inputs + `launcher.py` |
| `Build-WindowsApp.ps1` | PyInstaller onedir build |
| `Sync-From-Repo.ps1` | Refresh `app\` from repo root |
| `Launch-DACS-Baseline.bat` | Run exe if present, else run from `app\` |
| `dist\` | Build output (created by build script) |

## Notes

- Uses **system Chrome** (`channel=chrome`) for CAC — Playwright’s bundled
  Chromium is not used for scanning.
- Reports land in `reports\dd1348-irrd\<report-name-or-timestamp>\` next to the app.
- Failure screenshots go under each report’s `failure-screenshots\` folder.
