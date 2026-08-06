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
| `identifiers-full-462.txt` | Full unique list (**default scan input**, 462 IDs) |
| `identifiers.txt` | Working upload copy written per run |
| `QAReqsThatExistInDACS.xlsx` | Source workbook |

Refresh the full list from the xlsx:

```powershell
python -m dacs_baseline prep-ids --input input\QAReqsThatExistInDACS.xlsx
```
