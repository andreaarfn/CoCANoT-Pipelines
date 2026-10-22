$ErrorActionPreference = "Stop"
param()
$Prefix = Join-Path $env:LOCALAPPDATA "CoCANoT/runtime"
$Py = Join-Path $Prefix "python.exe"
foreach ($File in @($Py,(Join-Path $Prefix "CoCANoT.bat"),(Join-Path $Prefix "app/react_frontend/dist/index.html"),(Join-Path $Prefix "app/MetadataPipeline/dictionaries/CoCANoT_Metadata_Phase1.0.xlsx"))) {
  if (-not (Test-Path $File)) { throw "Missing: $File" }
}
& $Py -c "import webview, numpy, nibabel, pyedflib, fitz, openpyxl"
if ($LASTEXITCODE -ne 0) { throw "Python import verification failed" }
Write-Host "Windows native app verification passed."
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
  Write-Warning "WSL2 missing: MRI automatic defacing is unavailable."
} else {
  Write-Host "Check inside WSL: command -v pydeface && command -v flirt"
}
