# Input files

Default scan input: **`identifiers-full-462.txt`** (462 unique IDs from the spreadsheet).

```powershell
python -m dacs_baseline scan --label before
# uses input/identifiers-full-462.txt
```

## List Search flow

1. Upload the full ID list via **Or Upload a file** (`#fileInput`)
2. Select **Search By → TCN** (`#radio_TCN`)
3. Click **Search** (`#submitCriteriaBtn`)
4. Each result opens Details in a **new tab** → check Original DD1348 IRRD
   for **Click to Open** vs **Unavailable** → close tab → next result

## Files

| File | Notes |
|------|--------|
| `identifiers-full-462.txt` | Full unique list (462 IDs) |
| `identifiers-sample-10.txt` | Short list for quick tests (10 IDs) |
| `identifiers.txt` | Working upload copy written per run |
| `QAReqsThatExistInDACS.xlsx` | Source workbook |

## Choosing a file

```powershell
# File picker popup (default)
python -m dacs_baseline scan --label before --pick-input

# Or 10-ID sample, no picker
python -m dacs_baseline scan --label smoke --sample-10

# Or full list, no picker
python -m dacs_baseline scan --label before --no-pick-input --input input\identifiers-full-462.txt

# PowerShell helper (opens picker)
.\Run-Scan.ps1
.\Run-Scan.ps1 -Sample10
```
