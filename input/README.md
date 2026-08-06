# Input files

Drop Jeff’s spreadsheet here, then run `python -m dacs_baseline prep-ids` to
refresh `identifiers.txt`. Scans prefer the **txt** for List Search upload.

## List Search flow

1. Upload `identifiers.txt` (one shipment identifier per line) via **Or Upload a file** (`#fileInput`)
2. Select **Search By → Requisition** (`#radio_REQ` / `#searchBy`)
3. Click **Search** (`#submitCriteriaBtn`)

## Current files

| File | Notes |
|------|--------|
| `identifiers.txt` | Unique shipment identifiers for List Search upload (**preferred**) |
| `QAReqsThatExistInDACS.xlsx` | Source workbook (Shipment Identifier / RQSTN) |
