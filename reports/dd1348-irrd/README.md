# DD1348 IRRD scan reports

Scan output lands here:

```
reports/dd1348-irrd/<label>/
  had-dd1348.csv      # Original DD1348 IRRD = "Click to Open"
  no-dd1348.csv       # Original DD1348 IRRD = "Unavailable"
  all-results.csv     # every scanned identifier
  summary.txt         # counts + hit rate
```

Created at runtime by `python -m dacs_baseline scan --label before`.
