@echo off
setlocal
rem Constructor invokes this before removing the bundled CoCANoT runtime.
rem Only delete CoCANoT-owned local user data when the user explicitly agrees.
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" exit /b 1
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $result=[System.Windows.Forms.MessageBox]::Show('Also permanently delete CoCANoT local patient records, attachments, and settings from this Windows account? This cannot be undone. Source DICOM, NIfTI, EDF, and chosen output folders will not be removed.','Uninstall CoCANoT',[System.Windows.Forms.MessageBoxButtons]::YesNo,[System.Windows.Forms.MessageBoxIcon]::Warning,[System.Windows.Forms.MessageBoxDefaultButton]::Button2); if ($result -eq [System.Windows.Forms.DialogResult]::Yes) { exit 10 } else { exit 11 }"
set "REMOVE_DATA=%ERRORLEVEL%"
if "%REMOVE_DATA%"=="10" (
  rem Avoid following a reparse point/junction outside of the app's own data directory.
  "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$root=Join-Path $env:USERPROFILE '.cocanot'; if (Test-Path -LiteralPath $root) { $item=Get-Item -LiteralPath $root -Force; if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing to remove symlinked CoCANoT data directory.' }; if (-not $item.PSIsContainer) { throw 'Unexpected CoCANoT data path.' }; Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop; Write-Host 'Removed CoCANoT local patient data and settings.' }"
  if errorlevel 1 (echo WARNING: CoCANoT local data cleanup failed. & exit /b 1)
) else (
  echo CoCANoT local data retained. Remove-data option was declined.
)
rem The install creates these links outside the Conda runtime.
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$programs=[Environment]::GetFolderPath('Programs'); if ($programs) { $folder=Join-Path $programs 'CoCANoT'; Remove-Item -LiteralPath (Join-Path $programs 'CoCANoT.lnk') -Force -ErrorAction SilentlyContinue; foreach ($name in @('CoCANoT.lnk','Complete defacing setup.lnk','Uninstall defacing setup.lnk','Complete MRI defacing setup.lnk')) { Remove-Item -LiteralPath (Join-Path $folder $name) -Force -ErrorAction SilentlyContinue }; if (Test-Path -LiteralPath $folder) { $remaining=Get-ChildItem -LiteralPath $folder -Force; if (-not $remaining) { Remove-Item -LiteralPath $folder -Force } } }"
exit /b 0
