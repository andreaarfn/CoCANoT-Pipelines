# Optional, standalone cleanup of CoCANoT's Linux MRI defacing installations.
# WSL, Ubuntu and shared system packages are deliberately left untouched.
$ErrorActionPreference = 'Stop'
Write-Host 'CoCANoT defacing dependency removal' -ForegroundColor Cyan
Write-Host 'This removes the dedicated Ubuntu directories ~/cocanot-pydeface and ~/fsl.'
Write-Host 'It does NOT uninstall WSL2, Ubuntu, apt packages or other Linux environments.'
Write-Host 'WARNING: If you also use ~/fsl outside CoCANoT, do not proceed.'
$wslPath = Join-Path $env:WINDIR 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $wslPath)) {
    $wslCommand = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($null -eq $wslCommand) { throw 'WSL not found; no Ubuntu dependencies were removed.' }
    $wslPath = $wslCommand.Source
}
$distros = (& $wslPath --list --quiet 2>&1 | Out-String) -replace [char]0, ''
if ($LASTEXITCODE -ne 0) { throw 'Cannot list WSL distributions; no changes made.' }
$hasUbuntu = @(($distros -split '\r?\n') | Where-Object { $_.Trim() -eq 'Ubuntu' }).Count -gt 0
if (-not $hasUbuntu) { throw 'Ubuntu distribution not found. No changes made.' }

$inspect = @'
set -e
printf 'Ubuntu user: %s\n' "$(id -un)"
printf 'PyDeface virtual environment: '
if [ -d "$HOME/cocanot-pydeface" ]; then printf '%s\n' "$HOME/cocanot-pydeface"; else printf 'not found\n'; fi
printf 'FSL environment: '
if [ -d "$HOME/fsl" ]; then printf '%s\n' "$HOME/fsl"; else printf 'not found\n'; fi
'@
& $wslPath -d Ubuntu --exec bash -lc $inspect
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Ubuntu defacing installations. No changes made.' }
$answer = Read-Host 'Delete BOTH dedicated directories shown above from Ubuntu? Type REMOVE to confirm'
if ($answer -cne 'REMOVE') {
    Write-Host 'Cancelled. Nothing was removed.'
    exit 0
}
$removeScript = @'
set -eu
for name in cocanot-pydeface fsl; do
  candidate="$HOME/$name"
  # Refuse symlinked paths and prevent any chance of targeting HOME itself.
  if [ -L "$candidate" ]; then
    echo "ERROR: Refusing symbolic link: $candidate" >&2
    exit 1
  fi
  if [ -e "$candidate" ] && [ ! -d "$candidate" ]; then
    echo "ERROR: Not an ordinary directory: $candidate" >&2
    exit 1
  fi
done
for name in cocanot-pydeface fsl; do
  candidate="$HOME/$name"
  if [ -d "$candidate" ]; then
    rm -rf -- "$candidate"
    echo "Removed $candidate"
  else
    echo "Already absent: $candidate"
  fi
done
echo 'CoCANoT Linux defacing directories removed; Ubuntu and WSL retained.'
'@
$temporaryScript = Join-Path $env:TEMP ('cocanot-remove-defacing-' + [guid]::NewGuid().ToString('N') + '.sh')
try {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporaryScript, ($removeScript -replace "`r`n", "`n").TrimEnd() + "`n", $utf8)
    $linuxScript = (& $wslPath -d Ubuntu --exec wslpath -a -u $temporaryScript | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $linuxScript) { throw 'Failed to translate temporary script path; no changes made.' }
    & $wslPath -d Ubuntu --exec bash $linuxScript
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu defacing cleanup failed; inspect errors above.' }
} finally {
    Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
}
Write-Host 'SUCCESS: CoCANoT defacing dependency removal completed.' -ForegroundColor Green
Write-Host 'You can reinstall later using Start Menu > CoCANoT > Complete defacing setup.'
