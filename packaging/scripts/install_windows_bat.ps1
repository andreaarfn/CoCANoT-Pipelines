param(
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Revision
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Assert-Exit([string]$label) { if ($LASTEXITCODE -ne 0) { throw "$label failed (exit code $LASTEXITCODE)" } }
function Download([string]$url,[string]$to) {
  Write-Host "Downloading: $url"
  Invoke-WebRequest -Uri $url -OutFile $to -UseBasicParsing
  if (!(Test-Path $to) -or (Get-Item $to).Length -eq 0) { throw "Download failed: $url" }
}
if ([Environment]::Is64BitOperatingSystem -ne $true -or $env:PROCESSOR_ARCHITECTURE -notin @('AMD64')) {
  throw 'CoCANoT Windows setup requires Windows x64.'
}
$wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
if (!(Test-Path $wsl)) { throw 'WSL missing. Independently install WSL 2 and Ubuntu 24.04 LTS first: https://learn.microsoft.com/windows/wsl/install' }
# No wsl --install, --update, DISM or Windows feature modifications are allowed here.
$list = & $wsl --list --verbose 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { throw 'WSL is not ready. Install WSL 2, restart Windows if asked, and initialize Ubuntu 24.04 LTS first.' }
$cleanList = $list -replace [char]0, ''
if ($cleanList -notmatch '(?im)^\s*\*?\s*Ubuntu-24\.04\s+\S+\s+2\s*$') {
  throw "Ubuntu-24.04 running under WSL version 2 was not detected. Run 'wsl --list --verbose' and complete the manual WSL installation first."
}
& $wsl -d Ubuntu-24.04 --exec bash -lc 'id -u >/dev/null && test -d "$HOME"'
Assert-Exit 'Ubuntu-24.04 initialization check'
Write-Host 'Verified WSL 2 with initialized Ubuntu 24.04 LTS. WSL will not be modified.' -ForegroundColor Green
$homeDir = Join-Path $env:LOCALAPPDATA 'CoCANoT'
$runtime = Join-Path $homeDir 'runtime'
$workspace = Join-Path $homeDir 'installer-cache'
$miniforge = Join-Path $homeDir 'miniforge'
$nodeDir = Join-Path $homeDir 'node'
$repoZip = Join-Path $workspace 'source.zip'
$repoRoot = Join-Path $workspace ('CoCANoT-Pipelines-' + $Revision)
New-Item -ItemType Directory -Force -Path $homeDir,$workspace | Out-Null
if (!(Test-Path (Join-Path $repoRoot 'react_dashboard.py'))) {
  Download "https://github.com/andreaarfn/CoCANoT-Pipelines/archive/$Revision.zip" $repoZip
  Expand-Archive -LiteralPath $repoZip -DestinationPath $workspace -Force
}
if (!(Test-Path (Join-Path $repoRoot 'react_dashboard.py'))) { throw 'Source archive is missing expected project files.' }
if (!(Test-Path (Join-Path $miniforge 'Scripts\conda.exe'))) {
  $installer = Join-Path $workspace 'Miniforge3-Windows-x86_64.exe'
  Download 'https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe' $installer
  Write-Host 'Installing bundled Conda runtime for this Windows user...'
  $proc = Start-Process -FilePath $installer -ArgumentList @('/InstallationType=JustMe','/RegisterPython=0','/AddToPath=0',"/D=$miniforge") -Wait -PassThru
  if ($proc.ExitCode -ne 0) { throw "Miniforge installer failed: $($proc.ExitCode)" }
}
$conda = Join-Path $miniforge 'Scripts\conda.exe'
if (!(Test-Path $conda)) { throw 'Miniforge conda.exe is missing.' }
if (!(Test-Path (Join-Path $runtime 'python.exe'))) {
  Write-Host 'Installing native Windows Python, DICOM, image, EDF and metadata dependencies...'
  & $conda env create -y -p $runtime -f (Join-Path $repoRoot 'packaging\environment\environment-windows.yaml')
  Assert-Exit 'Conda environment creation'
}
$python = Join-Path $runtime 'python.exe'
& $python -m pip install -r (Join-Path $repoRoot 'packaging\environment\requirements-pip-windows.txt')
Assert-Exit 'Python package installation'
& $python -c 'import webview, numpy, nibabel, pyedflib, fitz, openpyxl, clr_loader, cffi, pythonnet'
Assert-Exit 'Windows Python dependency verification'
if (!(Test-Path (Join-Path $runtime 'Library\bin\dcm2niix.exe'))) { throw 'dcm2niix was not installed by Conda.' }
if (!(Test-Path (Join-Path $nodeDir 'node.exe'))) {
  $nodeZip = Join-Path $workspace 'node-v22.16.0-win-x64.zip'
  Download 'https://nodejs.org/dist/v22.16.0/node-v22.16.0-win-x64.zip' $nodeZip
  Expand-Archive -LiteralPath $nodeZip -DestinationPath $workspace -Force
  $extracted = Join-Path $workspace 'node-v22.16.0-win-x64'
  if (!(Test-Path (Join-Path $extracted 'node.exe'))) { throw 'Node archive is missing node.exe.' }
  Move-Item -LiteralPath $extracted -Destination $nodeDir
}
$env:PATH = "$nodeDir;$env:PATH"
Push-Location (Join-Path $repoRoot 'react_frontend')
try {
  & (Join-Path $nodeDir 'npm.cmd') ci
  Assert-Exit 'npm ci'
  & (Join-Path $nodeDir 'npm.cmd') run build
  Assert-Exit 'React frontend build'
} finally { Pop-Location }
$app = Join-Path $homeDir 'app'
New-Item -ItemType Directory -Force $app | Out-Null
foreach ($file in @('react_dashboard.py','pipeline_config.py')) { Copy-Item (Join-Path $repoRoot $file) $app -Force }
foreach ($folder in @('app','config','MetadataPipeline')) {
  Copy-Item (Join-Path $repoRoot $folder) (Join-Path $app $folder) -Recurse -Force
}
foreach ($folder in @('ImagingPipeline','ElectrophysiologyPipeline')) {
  New-Item -ItemType Directory -Force (Join-Path $app $folder) | Out-Null
  Copy-Item (Join-Path $repoRoot "$folder\scripts") (Join-Path $app $folder 'scripts') -Recurse -Force
}
New-Item -ItemType Directory -Force (Join-Path $app 'react_frontend') | Out-Null
Copy-Item (Join-Path $repoRoot 'react_frontend\dist') (Join-Path $app 'react_frontend\dist') -Recurse -Force
Copy-Item (Join-Path $repoRoot 'packaging\scripts\setup_windows_defacing.ps1') (Join-Path $app 'setup_windows_defacing.ps1') -Force
if (!(Test-Path (Join-Path $app 'react_frontend\dist\index.html'))) { throw 'React distribution missing after build.' }
$launcher = Join-Path $homeDir 'CoCANoT-Diagnostics.bat'
$lines = @('@echo off','set "PYTHONNOUSERSITE=1"',('set "PYTHONPATH=' + $app + '"'),('set "PATH=' + $runtime + ';' + (Join-Path $runtime 'Scripts') + ';' + (Join-Path $runtime 'Library\bin') + ';%PATH%"'),('cd /d "' + $app + '"'),('"' + $python + '" "' + (Join-Path $app 'react_dashboard.py') + '" %*'))
[IO.File]::WriteAllLines($launcher,$lines,[Text.Encoding]::ASCII)
$vbs = Join-Path $homeDir 'CoCANoT.vbs'
[IO.File]::WriteAllText($vbs, 'CreateObject("WScript.Shell").Run Chr(34) & "' + $launcher + '" & Chr(34), 0, False', [Text.Encoding]::ASCII)
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\CoCANoT'
New-Item -ItemType Directory -Force $startMenu | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startMenu 'CoCANoT.lnk'))
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$shortcut.Arguments = '"' + $vbs + '"'
$shortcut.WorkingDirectory = $homeDir
$shortcut.Save()
$deface = $shell.CreateShortcut((Join-Path $startMenu 'Install MRI defacing dependencies.lnk'))
$deface.TargetPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$deface.Arguments = '-NoProfile -ExecutionPolicy Bypass -NoExit -File "' + (Join-Path $app 'setup_windows_defacing.ps1') + '"'
$deface.WorkingDirectory = $app
$deface.Save()
Write-Host ''
Write-Host 'SUCCESS: CoCANoT is installed. Open it from the Start Menu.' -ForegroundColor Green
Write-Host 'For Imaging Step 3C, run Start Menu > CoCANoT > Install MRI defacing dependencies.'
Write-Host 'That separate utility installs FSL FLIRT/PyDeface INSIDE existing WSL 2 Ubuntu; it never installs WSL.'
Write-Host "Diagnostics launcher: $launcher"
