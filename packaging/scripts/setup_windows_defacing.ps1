# Optional, user-initiated Step 3C dependency setup. Never run during CoCANoT installation.
$ErrorActionPreference = 'Stop'
Write-Host 'CoCANoT MRI defacing setup (optional)' -ForegroundColor Cyan
Write-Host 'Steps 3A and 3B work without Linux. Step 3C needs WSL2, Ubuntu, FSL and PyDeface.'
Write-Host 'Setup can download several GB, require administrator approval, and require a Windows restart.'
Write-Host 'This utility will NEVER restart Windows for you.'
$consent = Read-Host 'Proceed with checking/installing Step 3C prerequisites? (type YES)'
if ($consent -cne 'YES') { Write-Host 'No changes made.'; exit 0 }
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
  Write-Host 'WSL is not available. Run PowerShell as Administrator and install WSL2.'
  exit 1
}
$distros = (& wsl.exe --list --quiet 2>&1 | Out-String) -replace [char]0, ''
$names = @($distros -split "`r?`n" | Where-Object { $_.Trim() -and $_ -notmatch 'Windows Subsystem|no installed|install|Error|Default' })
if ($LASTEXITCODE -ne 0 -or $names.Count -eq 0) {
  Write-Host 'No WSL distribution is installed. Ubuntu installation may enable Windows features and require a restart.' -ForegroundColor Yellow
  $answer = Read-Host 'Install Ubuntu through Windows WSL now? (type YES)'
  if ($answer -cne 'YES') { Write-Host 'No Ubuntu installation attempted.'; exit 0 }
  & wsl.exe --install -d Ubuntu
  if ($LASTEXITCODE -ne 0) { throw 'Ubuntu setup failed. Check messages above and run this utility again.' }
  Write-Host 'Complete any required Windows restart and Ubuntu first-run username/password setup. Then run this utility again.'
  exit 0
}
Write-Host "Available WSL distribution(s): $($names -join ', ')"
Write-Host 'FSL and PyDeface must run inside the default WSL distribution used by CoCANoT.'
$check = 'export FSLDIR="${FSLDIR:-$HOME/fsl}"; export PATH="$HOME/cocanot-pydeface/bin:$HOME/.local/bin:$FSLDIR/share/fsl/bin:$FSLDIR/bin:$PATH"; command -v pydeface && command -v flirt'
& wsl.exe --exec bash -lc $check
if ($LASTEXITCODE -eq 0) { Write-Host 'Step 3C prerequisites detected. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green; exit 0 }
Write-Host 'Linux FSL or PyDeface is missing.' -ForegroundColor Yellow
Write-Host 'FSL will be downloaded from its official installation site and can take substantial disk space.'
Write-Host 'PyDeface will be installed in ~/cocanot-pydeface (a Linux Python virtual environment).'
$agree = Read-Host 'Install Linux FSL (if missing) and PyDeface (if missing)? (type YES)'
if ($agree -cne 'YES') { Write-Host 'No Linux packages installed.'; exit 0 }
$install = @'
set -e
if ! command -v curl >/dev/null || ! command -v python3 >/dev/null || ! python3 -m venv --help >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y curl ca-certificates python3 python3-venv
fi
if [ ! -x "$HOME/fsl/share/fsl/bin/flirt" ] && ! command -v flirt >/dev/null 2>&1; then
  echo "Installing FSL from official FSL installer. Follow any on-screen prompts."
  curl -fLsS https://fsl.fmrib.ox.ac.uk/fsldownloads/fslconda/releases/getfsl.sh -o /tmp/cocanot-getfsl.sh
  sh /tmp/cocanot-getfsl.sh
fi
if [ ! -x "$HOME/cocanot-pydeface/bin/pydeface" ] && ! command -v pydeface >/dev/null 2>&1; then
  python3 -m venv "$HOME/cocanot-pydeface"
  "$HOME/cocanot-pydeface/bin/python" -m pip install --upgrade pip
  "$HOME/cocanot-pydeface/bin/python" -m pip install pydeface
fi
export FSLDIR="${FSLDIR:-$HOME/fsl}"
export PATH="$HOME/cocanot-pydeface/bin:$HOME/.local/bin:$FSLDIR/share/fsl/bin:$FSLDIR/bin:$PATH"
command -v pydeface
command -v flirt
echo "CoCANoT Step 3C Linux dependencies are available."
'@
# Use standard input to transmit the script safely; avoid interpolating shell commands in Windows.
$install | & wsl.exe --exec bash -s
if ($LASTEXITCODE -ne 0) { throw 'One or more Linux dependencies could not be installed. See the output above.' }
Write-Host 'Setup completed. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green
