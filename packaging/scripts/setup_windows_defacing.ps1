# Optional MRI Step 3C dependency installer. WSL2 and Ubuntu are user-managed.
$ErrorActionPreference = 'Stop'
Write-Host 'CoCANoT MRI defacing Linux dependency setup' -ForegroundColor Cyan
Write-Host 'WSL2 and Ubuntu must already be installed and initialized by the user.'
Write-Host 'Install WSL2/Ubuntu in an Administrator PowerShell: wsl --install -d Ubuntu'
Write-Host 'After any required restart, open Ubuntu once and create your Linux account.'
Write-Host 'Imaging Steps 3A/3B, metadata and electrophysiology do not require this setup.'
$wslPath = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $wslPath)) {
  $wslPath = (Get-Command wsl.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
}
if (-not $wslPath) {
  throw 'WSL is not installed. Run wsl --install -d Ubuntu from Administrator PowerShell, restart if prompted, and reopen this setup.'
}
# Check the Ubuntu distribution specifically; do not install or alter Windows features.
$listOutput = & $wslPath --list --verbose 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
  throw 'Could not query WSL distributions. Verify WSL2 is running with: wsl --list --verbose'
}
$cleanList = $listOutput -replace [char]0, ''
$ubuntuLine = @(($cleanList -split '\r?\n') | Where-Object { $_ -match '^\s*\*?\s*Ubuntu\s+' } | Select-Object -First 1)
if ($ubuntuLine.Count -eq 0) {
  throw 'Ubuntu is missing. Install it manually with: wsl --install -d Ubuntu'
}
if ($ubuntuLine[0] -notmatch '\s2\s*$') {
  throw 'Ubuntu must use WSL version 2. Run: wsl --set-version Ubuntu 2'
}
# The Windows MRI defacing runtime uses the default WSL distribution.
# Never change the user's WSL configuration silently; explain how to choose Ubuntu.
$defaultOutput = & $wslPath --list --verbose 2>&1 | Out-String
$defaultOutput = $defaultOutput -replace [char]0, ''
$defaultUbuntu = @(($defaultOutput -split '\r?\n') | Where-Object { $_ -match '^\s*\*\s*Ubuntu\s+' })
if ($defaultUbuntu.Count -eq 0) {
  throw 'CoCANoT Step 3C currently uses the default WSL distribution. In PowerShell, run: wsl --set-default Ubuntu, then retry this setup.'
}
# Avoid interactive first-run prompts in this installer.
& $wslPath -d Ubuntu --exec bash -lc 'id -u; test -d "$HOME"' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw 'Ubuntu is not initialized. Open Ubuntu from the Start menu, create a username/password, then retry.'
}
$check = 'export FSLDIR="${FSLDIR:-$HOME/fsl}"; export PATH="$HOME/cocanot-pydeface/bin:$HOME/.local/bin:$FSLDIR/share/fsl/bin:$FSLDIR/bin:$PATH"; command -v pydeface && command -v flirt && pydeface --help >/dev/null && flirt -version >/dev/null'
& $wslPath -d Ubuntu --exec bash -lc $check
if ($LASTEXITCODE -eq 0) {
  Write-Host 'SUCCESS: Step 3C dependencies detected. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green
  exit 0
}
$consent = Read-Host 'Install Linux FLIRT and PyDeface dependencies inside Ubuntu? (type YES)'
if ($consent -cne 'YES') {
  Write-Host 'Defacing dependency setup deferred. Step 3C remains unavailable.'
  exit 1
}
Write-Host 'Linux FSL or PyDeface is missing.' -ForegroundColor Yellow
Write-Host 'Only FSL FLIRT and its required runtime packages will be installed through micromamba.'
Write-Host 'PyDeface will be installed in ~/cocanot-pydeface (a Linux Python virtual environment).'
Write-Host 'Installing missing lightweight Linux dependencies as approved.'
Write-Host 'This can download Linux packages and may ask for your Ubuntu sudo password.'
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
  $linuxScript = (& $wslPath -d Ubuntu --exec wslpath -a -u $temporaryScript | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $linuxScript) { throw 'Could not translate Linux installer path into WSL.' }
  & $wslPath -d Ubuntu --exec bash $linuxScript
  $installExitCode = $LASTEXITCODE
} finally {
  Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
}
if ($installExitCode -ne 0) { throw "One or more Linux dependencies could not be installed (Ubuntu exit code $installExitCode). See the output above. You may retry using Start Menu > CoCANoT > Complete MRI defacing setup." }
& $wslPath -d Ubuntu --exec bash -lc $check
if ($LASTEXITCODE -ne 0) { throw 'FSL/PyDeface setup returned success but the required Linux tools are not accessible. Step 3C is NOT ready.' }
Write-Host 'SUCCESS: All Step 3C prerequisites detected. Restart CoCANoT and retry Step 3C.' -ForegroundColor Green
