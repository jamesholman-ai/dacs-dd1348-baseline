# Zip the built Windows app folder for copy to a VM.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$src = Join-Path $here 'dist\DACS-DD1348-Baseline'
if (-not (Test-Path (Join-Path $src 'DACS-DD1348-Baseline.exe'))) {
  throw "Build first: .\Build-WindowsApp.ps1"
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$zip = Join-Path $here "dist\DACS-DD1348-Baseline_$stamp.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $src -DestinationPath $zip -CompressionLevel Optimal
Write-Host "Created: $zip"
Write-Host ("Size: {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))
