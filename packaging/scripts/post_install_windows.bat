@echo off
setlocal
if "%PREFIX%"=="" (echo Missing constructor PREFIX & exit /b 1)
set "APPROOT=%PREFIX%\app"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL_EXE%" (echo Windows PowerShell executable missing: "%POWERSHELL_EXE%" & exit /b 1)
if not exist "%PREFIX%\python.exe" (echo Bundled Python missing & exit /b 1)
if not exist "%PREFIX%\payload\app_payload.zip" (echo App payload missing & exit /b 1)
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%PREFIX%\payload\app_payload.zip' -DestinationPath '%APPROOT%' -Force"
if errorlevel 1 exit /b 1
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%PREFIX%\payload\pip_packages.zip' -DestinationPath '%PREFIX%\payload\pip_packages' -Force"
if errorlevel 1 exit /b 1
"%PREFIX%\python.exe" -m pip install --no-index --no-deps --only-binary=:all: --find-links "%PREFIX%\payload\pip_packages" -r "%APPROOT%\packaging_requirements_pip.txt"
if errorlevel 1 exit /b 1
"%PREFIX%\python.exe" -c "import webview, numpy, nibabel, pyedflib, fitz, openpyxl, clr_loader, cffi, pythonnet"
if errorlevel 1 exit /b 1
if not exist "%PREFIX%\Library\bin\dcm2niix.exe" (echo Bundled dcm2niix.exe missing from Windows Conda runtime & exit /b 1)
if exist "%PREFIX%\CoCANoT.bat" del /q "%PREFIX%\CoCANoT.bat"
if not exist "%APPROOT%\react_frontend\dist\index.html" (echo React frontend missing & exit /b 1)
if not exist "%APPROOT%\MetadataPipeline\dictionaries\CoCANoT_Metadata_Phase1.0.xlsx" (echo Dictionary missing & exit /b 1)
> "%PREFIX%\CoCANoT-Diagnostics.bat" echo @echo off
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo set "PYTHONNOUSERSITE=1"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo set "PYTHONPATH=%APPROOT%"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo set "PATH=%PREFIX%;%PREFIX%\Scripts;%PREFIX%\Library\bin;%%PATH%%"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo cd /d "%APPROOT%"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo "%PREFIX%\python.exe" "%APPROOT%\react_dashboard.py" %%*
rem Only CoCANoT.vbs is the primary launcher; diagnostics batch is explicitly named.
> "%PREFIX%\CoCANoT.vbs" echo Set cocanotShell = CreateObject("WScript.Shell")
>> "%PREFIX%\CoCANoT.vbs" echo cocanotShell.Run Chr(34) ^& "%PREFIX%\CoCANoT-Diagnostics.bat" ^& Chr(34), 0, False
if errorlevel 1 exit /b 1
rem Create a normal Start Menu shortcut which launches without showing a console.
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$folder=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\CoCANoT'; New-Item -ItemType Directory -Force -Path $folder | Out-Null; $shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder 'CoCANoT.lnk')); $shortcut.TargetPath=Join-Path $env:SystemRoot 'System32\wscript.exe'; $shortcut.Arguments='"%PREFIX%\CoCANoT.vbs"'; $shortcut.WorkingDirectory='%PREFIX%'; $shortcut.Description='Launch CoCANoT without a console'; $shortcut.Save()"
if errorlevel 1 exit /b 1
if not exist "%APPROOT%\setup_windows_defacing.ps1" (echo Required MRI defacing setup utility missing & exit /b 1)
rem Required Step 3C dependency setup, with explicit consent for system changes.
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "$folder=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\CoCANoT'; $shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder 'Complete MRI defacing setup.lnk')); $shortcut.TargetPath=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'; $shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass -NoExit -File ""%APPROOT%\setup_windows_defacing.ps1""'; $shortcut.WorkingDirectory='%APPROOT%'; $shortcut.Description='Required Step 3C WSL2, FSL and PyDeface setup; may require restart'; $shortcut.Save()"
if errorlevel 1 exit /b 1
rem Show a clear setup notice during installation, not only in terminal output.
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('CoCANoT is installed, but Imaging Step 3C is NOT ready until MRI defacing setup is completed.' + [Environment]::NewLine + [Environment]::NewLine + 'NEXT: Open Start Menu > CoCANoT > Complete MRI defacing setup.' + [Environment]::NewLine + [Environment]::NewLine + 'The setup will guide you through WSL2, Ubuntu, FSL and PyDeface. Windows may require a restart; save your work before starting. CoCANoT will not restart Windows automatically.' + [Environment]::NewLine + [Environment]::NewLine + 'Steps 3A/3B, metadata and electrophysiology do not require this setup.', 'CoCANoT - Required imaging setup', 'OK', 'Information') | Out-Null"
echo CoCANoT installed. Launch from Start Menu CoCANoT or "%PREFIX%\CoCANoT.vbs".
echo For diagnostics run "%PREFIX%\CoCANoT-Diagnostics.bat" to see console output.
echo IMPORTANT: Complete MRI defacing setup from Start Menu before running Imaging Step 3C.
echo Defacing requires WSL2 with Linux FSL and PyDeface; native Windows FSL is not bundled.
exit /b 0
