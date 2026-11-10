# Optional, standalone cleanup of CoCANoT's Linux MRI defacing installations.
# WSL, Ubuntu and shared system packages are deliberately left untouched.
$ErrorActionPreference = 'Stop'
Write-Host 'CoCANoT defacing dependency removal' -ForegroundColor Cyan
Write-Host 'This removes ~/cocanot-pydeface, ~/fsl, and the CoCANoT micromamba cache.'
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
printf 'CoCANoT micromamba cache: '
if [ -d "$HOME/.local/share/cocanot-mamba" ]; then printf '%s\n' "$HOME/.local/share/cocanot-mamba"; else printf 'not found\n'; fi
'@
# Pass the inspection script as a UTF-8/LF file rather than via bash -lc.
# PowerShell/WSL argument quoting can corrupt multiline shell programs.
function Invoke-CoCANoTUbuntuScript {
    param([Parameter(Mandatory = $true)][string]$ScriptText)
    $temporaryScript = Join-Path $env:TEMP ('cocanot-defacing-' + [guid]::NewGuid().ToString('N') + '.sh')
    try {
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        $normalized = ($ScriptText -replace "`r`n", "`n" -replace "`r", "`n").TrimEnd() + "`n"
        [System.IO.File]::WriteAllText($temporaryScript, $normalized, $utf8)
        $linuxPath = (& $wslPath -d Ubuntu --exec wslpath -a -u $temporaryScript | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $linuxPath) {
            throw 'Could not translate temporary script path for Ubuntu.'
        }
        & $wslPath -d Ubuntu --exec bash $linuxPath
        if ($LASTEXITCODE -ne 0) {
            throw "Ubuntu script failed (exit code $LASTEXITCODE)."
        }
    } finally {
        Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
    }
}
try {
    Invoke-CoCANoTUbuntuScript -ScriptText $inspect
} catch {
    throw "Cannot inspect Ubuntu defacing installations. No changes made. $($_.Exception.Message)"
}
$answer = Read-Host 'Delete the CoCANoT defacing directories and cache shown above from Ubuntu? Type REMOVE to confirm'
if ($answer -cne 'REMOVE') {
    Write-Host 'Cancelled. Nothing was removed.'
    exit 0
}
$removeScript = @'
set -eu
for relative in cocanot-pydeface fsl .local/share/cocanot-mamba; do
  candidate="$HOME/$relative"
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
for relative in cocanot-pydeface fsl .local/share/cocanot-mamba; do
  candidate="$HOME/$relative"
  if [ -d "$candidate" ]; then
    rm -rf -- "$candidate"
    echo "Removed $candidate"
  else
    echo "Already absent: $candidate"
  fi
done
echo 'CoCANoT Linux defacing directories removed; Ubuntu and WSL retained.'
'@
Invoke-CoCANoTUbuntuScript -ScriptText $removeScript
Write-Host 'SUCCESS: CoCANoT defacing dependency removal completed.' -ForegroundColor Green
Write-Host 'You can reinstall later using Start Menu > CoCANoT > Complete defacing setup.'
