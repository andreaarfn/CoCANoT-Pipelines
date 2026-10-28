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
if not exist "%APPROOT%\react_frontend\dist\index.html" (echo React frontend missing & exit /b 1)
if not exist "%APPROOT%\MetadataPipeline\dictionaries\CoCANoT_Metadata_Phase1.0.xlsx" (echo Dictionary missing & exit /b 1)
> "%PREFIX%\CoCANoT.bat" echo @echo off
>> "%PREFIX%\CoCANoT.bat" echo set "PYTHONNOUSERSITE=1"
>> "%PREFIX%\CoCANoT.bat" echo set "PYTHONPATH=%APPROOT%"
>> "%PREFIX%\CoCANoT.bat" echo set "PATH=%PREFIX%;%PREFIX%\Scripts;%%PATH%%"
>> "%PREFIX%\CoCANoT.bat" echo cd /d "%APPROOT%"
>> "%PREFIX%\CoCANoT.bat" echo "%PREFIX%\python.exe" "%APPROOT%\react_dashboard.py" %%*
echo CoCANoT installed. Launch via "%PREFIX%\CoCANoT.bat".
echo Defacing requires WSL2 with Linux FSL and PyDeface; native Windows FSL is not bundled.
exit /b 0
