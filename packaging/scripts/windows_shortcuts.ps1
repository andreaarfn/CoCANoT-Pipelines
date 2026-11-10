param(
  [Parameter(Mandatory = $true)][string]$Prefix
)
$ErrorActionPreference = 'Stop'
$root = Join-Path $Prefix 'app'
$icon = Join-Path $root 'cocanot.ico'
$launcher = Join-Path $Prefix 'CoCANoT.vbs'
$setup = Join-Path $root 'setup_windows_defacing.ps1'
$uninstallSetup = Join-Path $root 'uninstall_windows_defacing.ps1'
foreach ($file in @($icon, $launcher, $setup, $uninstallSetup)) {
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing shortcut target: $file" }
}

# Constructor may run post-install under an elevated account. Derive the user
# profile from CoCANoT's standard per-user install directory when possible;
# relying on [Environment]::GetFolderPath('Programs') alone can write links
# into the administrator's Start Menu instead of the signed-in user's.
$profileMatch = [regex]::Match(
  $Prefix.TrimEnd([char]92, [char]47),
  '^(?<profile>.+?)[\\/]+AppData[\\/]+Local[\\/]+CoCANoT[\\/]+runtime$',
  [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
if ($profileMatch.Success) {
  $userHome = $profileMatch.Groups['profile'].Value
  $programs = Join-Path $userHome 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
} else {
  $programs = [Environment]::GetFolderPath('Programs')
}
if (-not $programs) { throw 'Could not resolve the destination Start Menu.' }
$folder = Join-Path $programs 'CoCANoT'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$logFile = Join-Path $Prefix 'shortcut-install.log'
"CoCANoT shortcut installation; Programs: $programs; Prefix: $Prefix" | Set-Content -LiteralPath $logFile -Encoding UTF8
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

# Separate optional cleanup utility. Do not remove Linux tools automatically
# when CoCANoT is uninstalled because FSL may be useful to other programs.
$uninstallLink = Join-Path $folder 'Uninstall defacing setup.lnk'
$cleanup = $shell.CreateShortcut($uninstallLink)
$cleanup.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$cleanup.Arguments = '-NoProfile -ExecutionPolicy Bypass -NoExit -File "' + $uninstallSetup + '"'
$cleanup.WorkingDirectory = $root
$cleanup.Description = 'Remove CoCANoT PyDeface and FSL installations from Ubuntu after confirmation'
$cleanup.IconLocation = "$icon,0"
$cleanup.Save()
if (-not (Test-Path -LiteralPath $uninstallLink -PathType Leaf)) { throw 'Defacing removal shortcut creation failed.' }

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
# Put the app itself at the top-level Programs folder, where Windows All apps
# indexes it directly. Keep the setup tools in the CoCANoT subfolder.
$appLink = Join-Path $programs 'CoCANoT.lnk'
$oldAppLink = Join-Path $folder 'CoCANoT.lnk'
if ($selected) {
  $shortcut = $shell.CreateShortcut($appLink)
  $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
  $shortcut.Arguments = '"' + $launcher + '"'
  $shortcut.WorkingDirectory = $Prefix
  $shortcut.Description = 'Launch CoCANoT'
  $shortcut.IconLocation = "$icon,0"
  $shortcut.Save()
  if (-not (Test-Path -LiteralPath $appLink -PathType Leaf)) { throw "CoCANoT shortcut not created: $appLink" }
  Remove-Item -LiteralPath $oldAppLink -Force -ErrorAction SilentlyContinue
  "Application shortcut created: $appLink" | Add-Content -LiteralPath $logFile
  Write-Host "Created application shortcut: $appLink"
} else {
  Remove-Item -LiteralPath $appLink -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $oldAppLink -Force -ErrorAction SilentlyContinue
  'Application shortcut declined' | Add-Content -LiteralPath $logFile
  Write-Host 'Application shortcut declined; defacing setup shortcut remains installed.'
}
Write-Host "Created defacing setup shortcut: $defacingLink"
Write-Host "Created defacing removal shortcut: $uninstallLink"

"Defacing setup: $defacingLink" | Add-Content -LiteralPath $logFile
"Defacing removal: $uninstallLink" | Add-Content -LiteralPath $logFile
