param(
  [Parameter(Mandatory = $true)][string]$Prefix
)
$ErrorActionPreference = 'Stop'
$root = Join-Path $Prefix 'app'
$icon = Join-Path $root 'cocanot.ico'
$launcher = Join-Path $Prefix 'CoCANoT.vbs'
$setup = Join-Path $root 'setup_windows_defacing.ps1'
foreach ($file in @($icon, $launcher, $setup)) {
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing shortcut target: $file" }
}

# Resolve the actual interactive user's Start Menu path, not the installer process's
# possibly elevated APPDATA directory.
$programs = [Environment]::GetFolderPath('Programs')
if (-not $programs) { throw 'Could not resolve the current user Start Menu.' }
$folder = Join-Path $programs 'CoCANoT'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$shell = New-Object -ComObject WScript.Shell
$oldShortcut = Join-Path $folder 'Complete MRI defacing setup.lnk'
Remove-Item -LiteralPath $oldShortcut -Force -ErrorAction SilentlyContinue

# The defacing setup must remain accessible even when the application shortcut
# is declined; this avoids making Step 3C impossible to configure.
$defacingLink = Join-Path $folder 'Complete defacing setup.lnk'
$defacing = $shell.CreateShortcut($defacingLink)
$defacing.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$defacing.Arguments = '-NoProfile -ExecutionPolicy Bypass -NoExit -File "' + $setup + '"'
$defacing.WorkingDirectory = $root
$defacing.Description = 'Install Linux PyDeface and FSL FLIRT for CoCANoT MRI defacing'
$defacing.IconLocation = "$icon,0"
$defacing.Save()
if (-not (Test-Path -LiteralPath $defacingLink -PathType Leaf)) { throw 'Defacing setup shortcut creation failed.' }

# Silent installs cannot display an interactive confirmation.
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
if ($selected) {
  $shortcut = $shell.CreateShortcut($appLink)
  $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
  $shortcut.Arguments = '"' + $launcher + '"'
  $shortcut.WorkingDirectory = $Prefix
  $shortcut.Description = 'Launch CoCANoT'
  $shortcut.IconLocation = "$icon,0"
  $shortcut.Save()
  if (-not (Test-Path -LiteralPath $appLink -PathType Leaf)) { throw "CoCANoT shortcut not created: $appLink" }
  Write-Host "Created application shortcut: $appLink"
} else {
  Remove-Item -LiteralPath $appLink -Force -ErrorAction SilentlyContinue
  Write-Host 'Application shortcut declined; defacing setup shortcut remains installed.'
}
Write-Host "Created defacing setup shortcut: $defacingLink"
