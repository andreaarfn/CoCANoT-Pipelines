# Required Step 3C provisioning. Runs only with explicit user consent; never reboots Windows automatically.
$ErrorActionPreference = 'Stop'
Write-Host 'CoCANoT MRI defacing required setup' -ForegroundColor Cyan
Write-Host 'Steps 3A and 3B work without Linux. Step 3C needs WSL2, Ubuntu, FSL and PyDeface.'
Write-Host 'Setup downloads only minimal FSL FLIRT packages (not full FSL); WSL may require administrator approval and a restart.'
Write-Host 'This utility will NEVER restart Windows for you.'
$consent = Read-Host 'Step 3C cannot run until these prerequisites are installed. Continue? (type YES)'
if ($consent -cne 'YES') { Write-Host 'Setup incomplete: Step 3C will remain unavailable.'; exit 1 }
# A clean Windows installation may have no WSL distribution or may need Windows features.
# Never disable features, replace a distribution, or reboot the computer automatically.
function Invoke-CoCANoTElevatedCommand([string]$command) {
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
  try {
    $process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded"
  } catch {
    throw "Administrator approval is required for WSL installation: $_"
  }
  return $process.ExitCode
}
$wslPath = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $wslPath)) {
  $wslPath = (Get-Command wsl.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
}
if (-not $wslPath) {
  Write-Host 'WSL executable is missing. CoCANoT can enable the Windows prerequisites.' -ForegroundColor Yellow
  $answer = Read-Host 'Enable WSL and Virtual Machine Platform with Administrator approval? (type YES)'
  if ($answer -cne 'YES') { Write-Host 'WSL installation deferred; Step 3C remains unavailable.'; exit 1 }
  $featureCommand = 'dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart; if ($LASTEXITCODE -notin @(0,3010)) { exit $LASTEXITCODE }; dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart; exit $LASTEXITCODE'
  $code = Invoke-CoCANoTElevatedCommand $featureCommand
  if ($code -notin @(0,3010)) { throw "Windows WSL feature installation failed (exit code $code)." }
  Write-Host 'Windows features enabled. Restart Windows manually if prompted, then reopen Start Menu > CoCANoT > Complete MRI defacing setup.' -ForegroundColor Yellow
  exit 0
}
# Do not conflate a failed WSL status check with an installed distribution.
$listOutput = & $wslPath --list --quiet 2>&1 | Out-String
$listCode = $LASTEXITCODE
$names = @()
if ($listCode -eq 0) {
  $names = @((($listOutput -replace [char]0, '') -split "`r?`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -notmatch 'Windows Subsystem|no installed|install|Error|Default' })
}
if ($names.Count -eq 0) {
  Write-Host 'Ubuntu is not ready. CoCANoT can request its installation with Administrator approval.' -ForegroundColor Yellow
  $answer = Read-Host 'Install WSL2 and Ubuntu for MRI defacing? (type YES)'
  if ($answer -cne 'YES') { Write-Host 'Ubuntu installation deferred; Step 3C remains unavailable.'; exit 1 }
  $quotedWsl = '"' + $wslPath.Replace('"','') + '"'
  $installCommand = "& $quotedWsl --install -d Ubuntu; exit `$LASTEXITCODE"
  $code = Invoke-CoCANoTElevatedCommand $installCommand
  if ($code -notin @(0,3010)) {
    throw "WSL/Ubuntu installation failed (exit code $code). Check administrator console output and Windows virtualization settings."
  }
  Write-Host 'Windows may require a manual restart or Ubuntu first-run username/password setup.' -ForegroundColor Yellow
  Write-Host 'Once Ubuntu is ready, reopen Start Menu > CoCANoT > Complete MRI defacing setup.'
  # Check only the named Ubuntu distro. Do not assume WSL --install completed initialization.
  & $wslPath -d Ubuntu --exec bash -lc 'id -u; test -d "$HOME"' 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) { exit 0 }
  Write-Host 'Ubuntu is initialized; proceeding with minimal FLIRT and PyDeface setup.' -ForegroundColor Green
}
Write-Host "Available WSL distribution(s): $($names -join ', ')"
Write-Host 'FSL and PyDeface must run inside the default WSL distribution used by CoCANoT.'
$check = 'export FSLDIR="${FSLDIR:-$HOME/fsl}"; export PATH="$HOME/cocanot-pydeface/bin:$HOME/.local/bin:$FSLDIR/share/fsl/bin:$FSLDIR/bin:$PATH"; command -v pydeface && command -v flirt && pydeface --help >/dev/null && flirt -version >/dev/null'
& wsl.exe --exec bash -lc $check
if ($LASTEXITCODE -eq 0) { Write-Host 'Step 3C prerequisites detected. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green; exit 0 }
Write-Host 'Linux FSL or PyDeface is missing.' -ForegroundColor Yellow
Write-Host 'Only FSL FLIRT and its required runtime packages will be installed through micromamba.'
Write-Host 'PyDeface will be installed in ~/cocanot-pydeface (a Linux Python virtual environment).'
$agree = Read-Host 'Install Linux FSL (if missing) and PyDeface (if missing)? (type YES)'
if ($agree -cne 'YES') { Write-Host 'Setup incomplete: FSL and PyDeface are required for Step 3C.'; exit 1 }
$install = @'
set -e
# Always verify/install the required Ubuntu packages. A PATH check alone can
# resolve Windows executables exposed through WSL, not usable Linux packages.
echo "Checking Ubuntu packages required by FSL and PyDeface (including bzip2)."
sudo apt-get update
sudo apt-get install -y curl ca-certificates bzip2 python3 python3-venv
if [ ! -x /usr/bin/bzip2 ]; then
  echo "ERROR: Ubuntu bzip2 is still missing after apt installation." >&2
  exit 1
fi
export PATH="/usr/bin:/bin:$PATH"
echo "Verified Linux bzip2: $(/usr/bin/bzip2 --help 2>&1 | head -n 1)"
# Reuse an existing usable Linux FLIRT install; never accept Windows .exe on WSL PATH.
if [ ! -x "$HOME/fsl/share/fsl/bin/flirt" ] && [ ! -x "$HOME/fsl/bin/flirt" ] && ! command -v flirt >/dev/null 2>&1; then
  echo "Installing minimal FSL FLIRT and required libraries (NOT the full FSL suite)."
  mkdir -p "$HOME/.local/bin"
  if [ ! -x "$HOME/.local/bin/micromamba" ]; then
    curl -fLsS https://micro.mamba.pm/api/micromamba/linux-64/latest -o /tmp/cocanot-micromamba.tar.bz2
    tar -xjf /tmp/cocanot-micromamba.tar.bz2 -C "$HOME/.local" bin/micromamba
    rm -f /tmp/cocanot-micromamba.tar.bz2
  fi
  export MAMBA_ROOT_PREFIX="$HOME/.local/share/cocanot-mamba"
  "$HOME/.local/bin/micromamba" create -y -p "$HOME/fsl" \
    --strict-channel-priority \
    -c https://fsl.fmrib.ox.ac.uk/fsldownloads/fslconda/public \
    -c conda-forge fsl-flirt
  # Minimize persistent disk usage without deleting installed environment.
  "$HOME/.local/bin/micromamba" clean --all --yes
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
pydeface --help >/dev/null
flirt -version
echo "Defacing dependency disk usage (MiB):"
du -sm "$HOME/fsl" "$HOME/cocanot-pydeface" 2>/dev/null || true
echo "CoCANoT Step 3C Linux dependencies are available."
'@
# Use standard input to transmit the script safely; avoid interpolating shell commands in Windows.
# PowerShell pipes text using Windows line endings; Bash expects LF.
# Pass a UTF-8/LF shell script as a temporary file through WSL's /mnt drive.
$temporaryScript = Join-Path $env:TEMP 'cocanot-install-linux-deps.sh'
try {
  $lfScript = ($install -replace "`r`n", "`n" -replace "`r", "`n").TrimEnd() + "`n"
  [System.IO.File]::WriteAllText($temporaryScript, $lfScript, (New-Object System.Text.UTF8Encoding($false)))
  $linuxScript = (& wsl.exe --exec wslpath -a -u $temporaryScript | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $linuxScript) { throw 'Could not translate Linux installer path into WSL.' }
  & wsl.exe --exec bash $linuxScript
  $installExitCode = $LASTEXITCODE
} finally {
  Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
}
if ($installExitCode -ne 0) { throw 'One or more Linux dependencies could not be installed. See the output above.' }
& wsl.exe --exec bash -lc $check
if ($LASTEXITCODE -ne 0) { throw 'FSL/PyDeface setup returned success but the required Linux tools are not accessible. Step 3C is NOT ready.' }
Write-Host 'All Step 3C prerequisites detected. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green
