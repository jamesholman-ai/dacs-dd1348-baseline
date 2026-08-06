# Input files

Scans prefer `identifiers.txt` for List Search. Smoke runs (`--max N`) upload a
**copy** under `reports/dd1348-irrd/<label>/list-search-upload.txt` and do **not**
overwrite this file.

## List Search flow

1. Upload `identifiers.txt` via **Or Upload a file** (`#fileInput`)
2. Select **Search By → TCN** (`#radio_TCN`)
3. Click **Search** (`#submitCriteriaBtn`)
4. Each result opens Details in a **new tab** → check Original DD1348 IRRD
   for **Click to Open** vs **Unavailable** → close tab → next result

## Current files

| File | Notes |
|------|--------|
| `identifiers.txt` | Unique shipment identifiers for List Search upload (**preferred**) |
| `QAReqsThatExistInDACS.xlsx` | Source workbook |
