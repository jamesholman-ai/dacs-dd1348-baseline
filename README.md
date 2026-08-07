# DACS DD1348 Baseline Scanner

Standalone Playwright tool that mirrors the EFTS Katalon **DACS Original DD1348 IRRD** baseline:

1. Load shipment identifiers from `./input/` (or txt/csv/xlsx you pass)
2. EFTS **Research → List Search** upload + Search
3. Open each **Shipment Identifier** Details tab (pings DACS)
4. Record whether Document Center `#originalDD1348irrd` returns a document vs **Unavailable**
5. Re-run with the same inputs after the query deploy and **compare** hit rates

Built for **gov-cloud Windows VMs with CAC**: uses installed **Chrome** + a persistent profile so Windows client certs work. You complete the PIN/cert prompt once per session.

## Click to run (recommended)

1. Copy the project folder to the VM (or unzip the package from `.\build_app.ps1`).
2. Double-click **`Start-DACS-Baseline.bat`**.
3. First run creates `.venv`, installs packages, and opens a **setup** dialog for:
   - working folder
   - input / reports / Chrome profile paths
   - EFTS URL and throttle / mid-run CAC timeout
4. Use the GUI to pick a label, optional **lines / skip lines / max**, then **Start Scan**.

Settings are saved in `user-settings.json` (local to that machine).

```powershell
# Same GUI from PowerShell
.\Run-Scan.ps1 -Gui

# Or package a shareable folder
.\build_app.ps1
# → dist\DACS-DD1348-Baseline\  (zip and copy; double-click the .bat inside)
```

## Input folder

Place Jeff’s spreadsheet in **`input/`**. On scan, a **file picker** opens so you
can choose which list to use:

- `input/identifiers-full-462.txt` — full run (462)
- `input/identifiers-sample-10.txt` — quick 10-ID test
- any other `.txt` / `.csv` / `.xlsx` you select

```powershell
python -m dacs_baseline scan --label before          # picker
python -m dacs_baseline scan --label smoke --sample-10
.\Run-Scan.ps1                                      # picker
.\Run-Scan.ps1 -Sample10
.\Run-Scan.ps1 -Lines "5-8"
.\Run-Scan.ps1 -SkipLines "1,3" -Max 20
```

Default **Search By** is **TCN** (`#radio_TCN`).

## Line selection

| Flag | Example | Meaning |
|------|---------|---------|
| `--max N` | `--max 10` | Only first N IDs (after other filters) |
| `--lines` | `--lines 5-8` or `1,3,10` | Only these 1-based lines from the file |
| `--skip-lines` | `--skip-lines 2,4` | Exclude these 1-based lines |
| `--start-index` | `--start-index 50` | Skip first N of the filtered list |

## Mid-run CAC failsafe

Initial CAC at login still uses `--cac-timeout-seconds` (default 10 minutes).

If a CAC / login window appears **again during** the scan, the tool waits up to
**5 minutes** (`--midrun-cac-timeout-seconds 300`), then **stops**, **writes
partial reports**, and records `early_stop_reason` in `summary.txt`.

## Details tab wait

After each List Search click, the tool waits for the Details tab to **open** and
for Document Center / Original DD1348 IRRD to **populate** (Click to Open or
Unavailable) before classifying:

```powershell
python -m dacs_baseline scan --label before --details-tab-timeout-seconds 300
```

Default is **300 seconds (5 minutes)**. Change it in first-run setup as
**Details tab populate wait**, or in `config.yaml` / `user-settings.json`.

## Locked report files

If Excel has `had-dd1348.csv` / `no-dd1348.csv` open, the tool writes
`*_OPEN_ME_*.csv` instead of crashing with `PermissionError`. Close Excel and
re-run, or use the stamped / `OPEN_ME` files.

## Setup (manual CLI)

```powershell
cd <project-folder>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional config:

```powershell
Copy-Item config.example.yaml config.yaml
# edit efts_url / throttle defaults
```

## Throttle (user choice)

| Flag | Meaning |
|------|---------|
| `--delay-seconds N` | Pause after every Details open (default 2) |
| `--batch-size N` | After every N opens, take a longer pause (`0` = off) |
| `--batch-pause-seconds N` | Length of that batch pause (default 30) |

Example gentle pacing:

```powershell
python -m dacs_baseline scan --label before `
  --delay-seconds 3 --batch-size 50 --batch-pause-seconds 60
```

## Commands

### Extract IDs from the spreadsheet in `input/`

```powershell
python -m dacs_baseline prep-ids
# writes input/identifiers.txt
```

### Baseline (before deploy)

```powershell
python -m dacs_baseline scan --label before `
  --efts-url https://test.scip.dsca.mil/NewEftsWeb/ `
  --delay-seconds 2 --batch-size 25 --batch-pause-seconds 45
```

Chrome opens → complete CAC → scanner runs. Reports under `reports/dd1348-irrd/<label>/`:

- `had-dd1348.csv` — Original DD1348 IRRD showed **Click to Open**
- `no-dd1348.csv` — showed **Unavailable**
- `all-results.csv` / `summary.txt`

### After deploy (identical process)

```powershell
python -m dacs_baseline scan --label after `
  --delay-seconds 2 --batch-size 25 --batch-pause-seconds 45
```

### Compare hit rates

```powershell
python -m dacs_baseline compare `
  --before reports\dd1348-irrd\before\all-results.csv `
  --after reports\dd1348-irrd\after\all-results.csv
```

## Smoke test a few IDs first

```powershell
python -m dacs_baseline scan --label smoke --max 5 --delay-seconds 2
# or: .\Run-Scan.ps1 -Label smoke
# or: .\Run-Scan.ps1 -Lines "1-5"
```

## Notes

- Selectors / flow ported from `Navsup.Wss.Efts.WebApps.Primary.Katalon` (`DacsDd1348BaselineWorkflow`, `EftsListSearchPage`).
- Flow: List Search by **TCN** → click result (**new tab**) → on that tab read **Original DD1348 IRRD** for **Click to Open** vs **Unavailable** → close tab → back to results → continue.
- Reports go to `reports/dd1348-irrd/<label>/` (`had-dd1348.csv` / `no-dd1348.csv`).
- `--search-by tcn|document|requisition|auto` overrides List Search radio.
- `--input path` still overrides `./input/` when you need a one-off file.
