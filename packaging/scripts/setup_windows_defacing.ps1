# CoCANoT Step 3C dependencies only. WSL 2 and Ubuntu 24.04 LTS are installed independently.
$ErrorActionPreference = 'Stop'
Write-Host 'CoCANoT MRI defacing dependencies (WSL is NOT installed or modified)' -ForegroundColor Cyan
$wslPath = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path $wslPath)) { throw 'Install WSL 2 and Ubuntu 24.04 LTS manually first: https://learn.microsoft.com/windows/wsl/install' }
$list = & $wslPath --list --verbose 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or (($list -replace [char]0, '') -notmatch '(?im)^\s*\*?\s*Ubuntu-24\.04\s+\S+\s+2\s*$')) {
  throw 'Required Ubuntu-24.04 under WSL version 2 was not found. Manually install and initialize WSL 2 / Ubuntu 24.04 LTS first.'
}
& $wslPath -d Ubuntu-24.04 --exec bash -lc 'id -u >/dev/null && test -d "$HOME"'
if ($LASTEXITCODE -ne 0) { throw 'Open Ubuntu 24.04 from the Start Menu and create your Linux account before proceeding.' }
$consent = Read-Host 'Install missing Linux FSL FLIRT / PyDeface dependencies in Ubuntu-24.04? (type YES)'
if ($consent -cne 'YES') { Write-Host 'Setup cancelled.'; exit 1 }
function Clear-CoCANoTResume { }
$check = 'export FSLDIR="${FSLDIR:-$HOME/fsl}"; export PATH="$HOME/cocanot-pydeface/bin:$HOME/.local/bin:$FSLDIR/share/fsl/bin:$FSLDIR/bin:$PATH"; command -v pydeface && command -v flirt && pydeface --help >/dev/null && flirt -version >/dev/null'
& $wslPath -d Ubuntu-24.04 --exec bash -lc $check
if ($LASTEXITCODE -eq 0) { Clear-CoCANoTResume; Write-Host 'SUCCESS: Step 3C dependencies detected. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green; exit 0 }
Write-Host 'Linux FSL or PyDeface is missing.' -ForegroundColor Yellow
Write-Host 'Only FSL FLIRT and its required runtime packages will be installed through micromamba.'
Write-Host 'PyDeface will be installed in ~/cocanot-pydeface (a Linux Python virtual environment).'
Write-Host 'Step 3/3: Installing missing lightweight Linux dependencies as approved.'
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
  $linuxScript = (& $wslPath -d Ubuntu-24.04 --exec wslpath -a -u $temporaryScript | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $linuxScript) { throw 'Could not translate Linux installer path into WSL.' }
  & $wslPath -d Ubuntu-24.04 --exec bash $linuxScript
  $installExitCode = $LASTEXITCODE
} finally {
  Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
}
if ($installExitCode -ne 0) { throw 'One or more Linux dependencies could not be installed. See the output above.' }
& $wslPath -d Ubuntu-24.04 --exec bash -lc $check
if ($LASTEXITCODE -ne 0) { throw 'FSL/PyDeface setup returned success but the required Linux tools are not accessible. Step 3C is NOT ready.' }
Clear-CoCANoTResume
Write-Host 'SUCCESS: All Step 3C prerequisites detected. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green
