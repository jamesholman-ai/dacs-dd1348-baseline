# Input files

Drop Jeff’s spreadsheet (or a `.txt` / `.csv` of identifiers) here.

When you run `python -m dacs_baseline scan` with no `--input`, the tool picks from this folder:

1. `QAReqsThatExistInDACS.xlsx` (preferred)
2. `identifiers.txt` / `identifiers.csv`
3. Otherwise the newest `.xlsx` / `.csv` / `.txt` in this folder

## Current files

| File | Notes |
|------|--------|
| `QAReqsThatExistInDACS.xlsx` | Source workbook (Shipment Identifier / RQSTN) |
| `identifiers.txt` | Unique IDs extracted for List Search upload |

Replace or add files as needed; no Downloads path required.
