param(
  [Parameter(Mandatory = $true)][string]$Prefix
)
$ErrorActionPreference = 'Stop'
$root = Join-Path $Prefix 'app'
$icon = Join-Path $root 'cocanot.ico'
$launcher = Join-Path $Prefix 'CoCANoT.vbs'
$diagnostics = Join-Path $Prefix 'CoCANoT-Diagnostics.bat'
$setup = Join-Path $root 'setup_windows_defacing.ps1'
$uninstallSetup = Join-Path $root 'uninstall_windows_defacing.ps1'
$logFile = Join-Path $Prefix 'shortcut-install.log'

# Constructor can execute as a different Windows account. For a standard
# CoCANoT install, derive the target user's Start Menu from the actual prefix.
$profileMatch = [regex]::Match(
  $Prefix.TrimEnd([char]92, [char]47),
  '^(?<profile>.+?)[\\/]+AppData[\\/]+Local[\\/]+CoCANoT[\\/]+runtime$',
  [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
$programs = [Environment]::GetFolderPath('Programs')
if ($profileMatch.Success) {
  $userHome = $profileMatch.Groups['profile'].Value
  $candidate = Join-Path $userHome 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
  if (Test-Path -LiteralPath (Split-Path $candidate -Parent) -PathType Container) {
    $programs = $candidate
  }
}
if (-not $programs) { throw 'Could not determine the Windows Start Menu location.' }
$folder = Join-Path $programs 'CoCANoT'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
"CoCANoT shortcut creation. Prefix=$Prefix; Programs=$programs" | Set-Content -LiteralPath $logFile -Encoding UTF8
$shell = New-Object -ComObject WScript.Shell

function Write-Link {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$Target,
    [string]$Arguments = '',
    [string]$Description = '',
    [string]$WorkingDirectory = $Prefix
  )
  if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
    "WARNING: Skipping $Path because target is missing: $Target" | Add-Content -LiteralPath $logFile
    return $false
  }
  try {
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.WorkingDirectory = $WorkingDirectory
    $link.Description = $Description
    if (Test-Path -LiteralPath $icon -PathType Leaf) {
      $link.IconLocation = "$icon,0"
    }
    $link.Save()
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
      throw "Shortcut file was not created: $Path"
    }
    "Created: $Path -> $Target $Arguments" | Add-Content -LiteralPath $logFile
    Write-Host "Created Start Menu shortcut: $Path"
    return $true
  } catch {
    "WARNING: Could not create $Path : $($_.Exception.Message)" | Add-Content -LiteralPath $logFile
    Write-Warning "Could not create Start Menu shortcut $Path : $($_.Exception.Message)"
    return $false
  }
}

# The main application does not depend on the optional WSL setup scripts.
$unattended = $env:INSTALLER_UNATTENDED -eq '1'
$selected = $true
if (-not $unattended) {
  Add-Type -AssemblyName System.Windows.Forms
  $response = [System.Windows.Forms.MessageBox]::Show(
    'Would you like a CoCANoT shortcut in your Windows Start Menu?',
    'CoCANoT Installation',
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question,
    [System.Windows.Forms.MessageBoxDefaultButton]::Button1
  )
  $selected = $response -eq [System.Windows.Forms.DialogResult]::Yes
}
$appLink = Join-Path $folder 'CoCANoT.lnk'
$rootLink = Join-Path $programs 'CoCANoT.lnk'
if ($selected) {
  $wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
  if ((Test-Path -LiteralPath $launcher -PathType Leaf) -and
      (Test-Path -LiteralPath $diagnostics -PathType Leaf)) {
    $success = Write-Link -Path $appLink -Target $wscript -Arguments ('"' + $launcher + '"') -Description 'Launch CoCANoT'
    if ($success) {
      # Also make the application easy to find in the Windows All apps list.
      [void](Write-Link -Path $rootLink -Target $wscript -Arguments ('"' + $launcher + '"') -Description 'Launch CoCANoT')
    }
  } else {
    "WARNING: CoCANoT launcher files missing. Expected $launcher and $diagnostics" | Add-Content -LiteralPath $logFile
    Write-Warning 'Main CoCANoT launchers do not exist; no invalid app shortcut created.'
  }
} else {
  Remove-Item -LiteralPath $appLink, $rootLink -Force -ErrorAction SilentlyContinue
  'Application Start Menu shortcut declined.' | Add-Content -LiteralPath $logFile
}

# Optional tools are independent of the application shortcut and each other.
$powershellExe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (Test-Path -LiteralPath $setup -PathType Leaf) {
  [void](Write-Link -Path (Join-Path $folder 'Complete defacing setup.lnk') -Target $powershellExe -Arguments ('-NoProfile -ExecutionPolicy Bypass -NoExit -File "' + $setup + '"') -WorkingDirectory $root -Description 'Install CoCANoT PyDeface and FSL in Ubuntu')
}
if (Test-Path -LiteralPath $uninstallSetup -PathType Leaf) {
  [void](Write-Link -Path (Join-Path $folder 'Uninstall defacing setup.lnk') -Target $powershellExe -Arguments ('-NoProfile -ExecutionPolicy Bypass -NoExit -File "' + $uninstallSetup + '"') -WorkingDirectory $root -Description 'Remove CoCANoT Linux defacing components after confirmation')
}
Remove-Item -LiteralPath (Join-Path $folder 'Complete MRI defacing setup.lnk') -Force -ErrorAction SilentlyContinue
Write-Host "Shortcut details saved to: $logFile"
