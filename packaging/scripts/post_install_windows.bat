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
rem Verify all major Windows application and imaging runtime dependencies were installed.
"%PREFIX%\python.exe" -c "import flask, yaml, PIL, matplotlib, scipy, scipy.ndimage, requests, networkx, nipype, traits, tkinter"
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
rem Set up Start Menu links through a standalone PowerShell script to avoid
rem CMD/PowerShell nested-quote errors and verify created .lnk files.
if not exist "%APPROOT%\windows_shortcuts.ps1" (echo Windows shortcut helper missing & exit /b 1)
"%POWERSHELL_EXE%" -NoProfile -STA -ExecutionPolicy Bypass -File "%APPROOT%\windows_shortcuts.ps1" -Prefix "%PREFIX%"
if errorlevel 1 exit /b 1
rem Do not automatically launch the defacing assistant after app installation.
rem Users can optionally open it through the Start Menu shortcut after installing WSL2 and Ubuntu.
echo CoCANoT installed. Launch from the optional Start Menu shortcut or "%PREFIX%\CoCANoT.vbs".
echo For diagnostics run "%PREFIX%\CoCANoT-Diagnostics.bat" to see console output.
echo Imaging Step 3C: Install WSL2 Ubuntu yourself using: wsl --install -d Ubuntu
echo After Ubuntu initialization, use Start Menu ^> CoCANoT ^> Complete defacing setup to install FLIRT and PyDeface.
echo Defacing requires WSL2 with Linux FSL and PyDeface; native Windows FSL is not bundled.
exit /b 0
