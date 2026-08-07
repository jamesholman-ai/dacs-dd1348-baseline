# Fast helpers for the gov-cloud VM. Edit throttle / line filters as needed.

param(
  [ValidateSet('before','after','smoke','pick')]
  [string]$Label = 'pick',
  [double]$DelaySeconds = 2,
  [int]$BatchSize = 25,
  [double]$BatchPauseSeconds = 45,
  [int]$Max = 0,
  [string]$Lines = '',
  [string]$SkipLines = '',
  [switch]$NoPick,
  [switch]$Sample10,
  [switch]$Gui
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

if ($Gui) {
  & .\.venv\Scripts\python.exe -m dacs_baseline
  exit $LASTEXITCODE
}

# Default: open a file picker so you choose full-462, sample-10, etc.
$runLabel = if ($Label -eq 'pick') { 'before' } else { $Label }

$argsList = @(
  '-m', 'dacs_baseline', 'scan',
  '--label', $runLabel,
  '--delay-seconds', "$DelaySeconds",
  '--batch-size', "$BatchSize",
  '--batch-pause-seconds', "$BatchPauseSeconds"
)

if ($Sample10 -or $Label -eq 'smoke') {
  $argsList += @('--sample-10', '--no-pick-input')
  if ($Label -eq 'smoke') {
    $argsList = @(
      '-m', 'dacs_baseline', 'scan',
      '--label', 'smoke',
      '--sample-10',
      '--no-pick-input',
      '--delay-seconds', "$DelaySeconds"
    )
  }
} elseif ($NoPick) {
  $argsList += @(
    '--no-pick-input',
    '--input', 'input\identifiers-full-462.txt'
  )
} else {
  $argsList += @('--pick-input')
}

if ($Max -gt 0) { $argsList += @('--max', "$Max") }
if ($Lines) { $argsList += @('--lines', $Lines) }
if ($SkipLines) { $argsList += @('--skip-lines', $SkipLines) }

Write-Host "Running: python $($argsList -join ' ')"
& .\.venv\Scripts\python.exe @argsList
