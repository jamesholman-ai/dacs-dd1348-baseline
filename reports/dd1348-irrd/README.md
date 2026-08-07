# DD1348 IRRD scan reports

Scan output lands here:

```
reports/dd1348-irrd/<report-name-or-timestamp>/
  all-results.csv     # every identifier (incl. early-stop placeholders)
  had-dd1348.csv      # Original DD1348 IRRD = "Click to Open"
  no-dd1348.csv       # Original DD1348 IRRD = "Unavailable"
  summary.txt         # counts + hit rate + resume hint
  run-state.json      # used by --resume
```

- Named: `python -m dacs_baseline scan --report-name before-deploy-1`
- No name: timestamp folder, e.g. `20260807_111530`
- Resume: `python -m dacs_baseline scan --resume` (or `--resume <name-or-path>`)
