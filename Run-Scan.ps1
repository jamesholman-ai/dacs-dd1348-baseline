# Fast helpers for the gov-cloud VM. Edit throttle flags as needed.

param(
  [ValidateSet('before','after','smoke')]
  [string]$Label = 'before',
  [double]$DelaySeconds = 2,
  [int]$BatchSize = 25,
  [double]$BatchPauseSeconds = 45,
  [int]$Max = 0
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

$argsList = @(
  '-m', 'dacs_baseline', 'scan',
  '--label', $Label,
  '--input', 'input\identifiers-full-462.txt',
  '--delay-seconds', "$DelaySeconds",
  '--batch-size', "$BatchSize",
  '--batch-pause-seconds', "$BatchPauseSeconds"
)
if ($Max -gt 0) { $argsList += @('--max', "$Max") }
if ($Label -eq 'smoke') {
  $argsList = @(
    '-m', 'dacs_baseline', 'scan',
    '--label', 'smoke',
    '--input', 'input\identifiers-full-462.txt',
    '--max', '5',
    '--delay-seconds', "$DelaySeconds"
  )
}

Write-Host "Running: python $($argsList -join ' ')"
& .\.venv\Scripts\python.exe @argsList
