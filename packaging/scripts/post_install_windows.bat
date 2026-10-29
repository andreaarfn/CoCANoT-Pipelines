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
"%PREFIX%\python.exe" -m pip install --no-index --only-binary=:all: --find-links "%PREFIX%\payload\pip_packages" -r "%APPROOT%\packaging_requirements_pip.txt"
if errorlevel 1 exit /b 1
"%PREFIX%\python.exe" -c "import webview, numpy, nibabel, pyedflib, fitz, openpyxl, clr_loader, cffi, pythonnet, pyfacewipe, torch"
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
echo CoCANoT installed. Launch from Start Menu CoCANoT or "%PREFIX%\CoCANoT.vbs".
echo For diagnostics run "%PREFIX%\CoCANoT-Diagnostics.bat" to see console output.
echo Imaging Step 3C uses native PyFaceWipe; WSL and FSL are not required.
exit /b 0
