# Input files

Drop Jeff’s spreadsheet here, then run `python -m dacs_baseline prep-ids` to
refresh `identifiers.txt`. Scans prefer the **txt** for List Search upload.

## List Search flow

1. Upload `identifiers.txt` via **Or Upload a file** (`#fileInput`)
2. Select **Search By → TCN** (`#radio_TCN`)
3. Click **Search** (`#submitCriteriaBtn`)
4. Each result opens Details in a **new tab** → check Original DD1348 IRRD
   for **Click to Open** vs **Unavailable** → close tab → next result

## Current files

| File | Notes |
|------|--------|
| `identifiers-full-462.txt` | Full unique list from the spreadsheet (**preferred**, 462 IDs) |
| `identifiers.txt` | Working List Search upload list |
| `QAReqsThatExistInDACS.xlsx` | Source workbook |
