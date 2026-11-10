$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$Stage = Join-Path $ProjectRoot "packaging/stage-windows"
$Construct = Join-Path $ProjectRoot "packaging/constructor/windows"
if ($env:OS -ne "Windows_NT") { throw "Build the Windows installer on Windows x64 (or a Windows VM)." }
if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") { throw "This packaging target requires Windows x64." }
if (-not $env:CONDA_PREFIX) { throw "Activate a Windows x64 Conda build environment." }
$Py = Join-Path $env:CONDA_PREFIX "python.exe"
if (-not (Test-Path $Py)) { throw "Bundled build Python missing: $Py" }
if (-not (Get-Command constructor -ErrorAction SilentlyContinue)) { throw "Install conda constructor." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Install Node.js/npm on the build machine." }
& $Py (Join-Path $ProjectRoot "packaging/scripts/audit_runtime_dependencies.py") --platform windows
if ($LASTEXITCODE -ne 0) { throw "Windows pipeline dependency audit failed" }
Push-Location (Join-Path $ProjectRoot "react_frontend")
try {
  & npm ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
  & npm run build
  if ($LASTEXITCODE -ne 0) { throw "React build failed" }
} finally { Pop-Location }
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
$Payload = Join-Path $Stage "app"
$Wheels = Join-Path $Stage "wheels"
New-Item -ItemType Directory -Force $Payload,$Wheels | Out-Null
# Use the existing CoCANoT logo for Windows Start Menu shortcuts.
$LogoPng = Join-Path $ProjectRoot "assets/logo/logo-1024.png"
$IconIco = Join-Path $Payload "cocanot.ico"
if (-not (Test-Path $LogoPng)) { throw "CoCANoT source logo missing: $LogoPng" }
$IconScript = @'
import sys
from PIL import Image
source, target = sys.argv[1:3]
with Image.open(source) as img:
    img.convert("RGBA").save(target, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
'@
$IconScript | & $Py - $LogoPng $IconIco
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $IconIco)) { throw "CoCANoT Windows icon generation failed (Pillow required on build runner)." }
Write-Host "Prepared Windows application icon: $IconIco"
Copy-Item (Join-Path $ProjectRoot "react_dashboard.py") $Payload
Copy-Item (Join-Path $ProjectRoot "pipeline_config.py") $Payload
Copy-Item (Join-Path $ProjectRoot "packaging/scripts/setup_windows_defacing.ps1") (Join-Path $Payload "setup_windows_defacing.ps1")
Copy-Item (Join-Path $ProjectRoot "packaging/scripts/windows_shortcuts.ps1") (Join-Path $Payload "windows_shortcuts.ps1")
Copy-Item (Join-Path $ProjectRoot "packaging/environment/requirements-pip-windows.txt") (Join-Path $Payload "packaging_requirements_pip.txt")
foreach ($dir in @("app","config","MetadataPipeline")) {
  Copy-Item (Join-Path $ProjectRoot $dir) $Payload -Recurse
}
foreach ($dir in @("ImagingPipeline","ElectrophysiologyPipeline")) {
  New-Item -ItemType Directory -Force (Join-Path $Payload $dir) | Out-Null
  Copy-Item (Join-Path $ProjectRoot "$dir/scripts") (Join-Path $Payload $dir) -Recurse
}
New-Item -ItemType Directory -Force (Join-Path $Payload "react_frontend") | Out-Null
Copy-Item (Join-Path $ProjectRoot "react_frontend/dist") (Join-Path $Payload "react_frontend") -Recurse
Get-ChildItem $Payload -Recurse -Directory -Filter __pycache__ | Remove-Item -Force -Recurse
Get-ChildItem $Payload -Recurse -File -Filter *.pyc | Remove-Item -Force
$BinaryRequirements = Join-Path $Stage "binary-requirements.txt"
Get-Content (Join-Path $ProjectRoot "packaging/environment/requirements-pip-windows.txt") |
  Where-Object { $_ -notmatch '^proxy-tools==' } | Set-Content $BinaryRequirements
& $Py -m pip wheel --wheel-dir $Wheels --no-deps "proxy-tools==0.1.0"
if ($LASTEXITCODE -ne 0) { throw "proxy-tools wheel build failed" }
& $Py -m pip download --dest $Wheels --only-binary=:all: --no-deps -r $BinaryRequirements
if ($LASTEXITCODE -ne 0) { throw "Windows wheel download failed" }
# Explicitly verify Windows desktop bridge dependencies are bundled for offline installs.
foreach ($package in @("pythonnet", "clr_loader", "cffi", "pycparser", "pywebview", "nipype", "requests", "traits", "networkx")) {
  $found = Get-ChildItem $Wheels -File -Filter "*.whl" | Where-Object {
    $_.Name -match ("^" + [regex]::Escape($package) + "-")
  }
  if (-not $found) { throw "Missing Windows installer wheel: $package" }
  Write-Host "Bundled Windows dependency: $package"
}
# Fail the GitHub build if required setup scripts or the frontend payload are absent.
foreach ($required in @("setup_windows_defacing.ps1", "windows_shortcuts.ps1", "packaging_requirements_pip.txt", "react_frontend/dist/index.html", "cocanot.ico")) {
  if (-not (Test-Path (Join-Path $Payload $required))) { throw "Missing Windows installer payload file: $required" }
}
Compress-Archive -Path (Join-Path $Payload "*") -DestinationPath (Join-Path $Stage "app_payload.zip") -Force
Compress-Archive -Path (Join-Path $Wheels "*") -DestinationPath (Join-Path $Stage "pip_packages.zip") -Force
Push-Location $Construct
try {
  & constructor .
  if ($LASTEXITCODE -ne 0) { throw "Constructor build failed" }
} finally { Pop-Location }
$Exe = Join-Path $Construct "CoCANoT-Windows-x64.exe"
if (-not (Test-Path $Exe)) { throw "Installer missing: $Exe" }
Write-Host "Built: $Exe"
