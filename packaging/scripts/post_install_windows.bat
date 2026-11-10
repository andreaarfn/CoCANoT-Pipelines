@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem This runs inside the Windows Constructor installer with PREFIX supplied.
if "%PREFIX%"=="" (echo ERROR: Missing constructor PREFIX & exit /b 1)
set "APPROOT=%PREFIX%\app"
set "LOG=%PREFIX%\cocanot-post-install.log"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
> "%LOG%" echo CoCANoT post-install started for "%PREFIX%"
set "STEP=preflight"
if not exist "%POWERSHELL_EXE%" (echo ERROR: PowerShell missing >> "%LOG%" & goto :fail)
if not exist "%PREFIX%\python.exe" (echo ERROR: Bundled Python missing >> "%LOG%" & goto :fail)
if not exist "%PREFIX%\payload\app_payload.zip" (echo ERROR: Application archive missing >> "%LOG%" & goto :fail)
if not exist "%PREFIX%\payload\pip_packages.zip" (echo ERROR: Python dependency archive missing >> "%LOG%" & goto :fail)

set "STEP=unpack application"
>> "%LOG%" echo Starting: %STEP%
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%PREFIX%\payload\app_payload.zip' -DestinationPath '%APPROOT%' -Force" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

set "STEP=unpack wheels"
>> "%LOG%" echo Starting: %STEP%
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%PREFIX%\payload\pip_packages.zip' -DestinationPath '%PREFIX%\payload\pip_packages' -Force" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

set "STEP=install bundled Python packages"
>> "%LOG%" echo Starting: %STEP%
"%PREFIX%\python.exe" -m pip install --no-index --no-deps --only-binary=:all: --find-links "%PREFIX%\payload\pip_packages" -r "%APPROOT%\packaging_requirements_pip.txt" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

set "STEP=verify desktop bridge"
>> "%LOG%" echo Starting: %STEP%
"%PREFIX%\python.exe" -c "import webview, numpy, nibabel, pyedflib, fitz, openpyxl, clr_loader, cffi, pythonnet" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

set "STEP=verify pipeline dependencies"
>> "%LOG%" echo Starting: %STEP%
"%PREFIX%\python.exe" -c "import flask, yaml, PIL, matplotlib, scipy, scipy.ndimage, requests, networkx, nipype, traits, tkinter" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

set "STEP=verify installed payload"
>> "%LOG%" echo Starting: %STEP%
if not exist "%PREFIX%\Library\bin\dcm2niix.exe" (echo ERROR: dcm2niix.exe missing >> "%LOG%" & goto :fail)
if not exist "%APPROOT%\react_frontend\dist\index.html" (echo ERROR: React frontend missing >> "%LOG%" & goto :fail)
if not exist "%APPROOT%\MetadataPipeline\dictionaries\CoCANoT_Metadata_Phase1.0.xlsx" (echo ERROR: Metadata dictionary missing >> "%LOG%" & goto :fail)
if not exist "%APPROOT%\windows_shortcuts.ps1" (echo WARNING: Shortcut helper missing >> "%LOG%")
if not exist "%APPROOT%\cocanot.ico" (echo WARNING: App icon missing >> "%LOG%")
if exist "%PREFIX%\CoCANoT.bat" del /q "%PREFIX%\CoCANoT.bat"

set "STEP=create application launcher"
>> "%LOG%" echo Starting: %STEP%
> "%PREFIX%\CoCANoT-Diagnostics.bat" echo @echo off
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo set "PYTHONNOUSERSITE=1"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo set "PYTHONPATH=%APPROOT%"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo set "PATH=%PREFIX%;%PREFIX%\Scripts;%PREFIX%\Library\bin;%%PATH%%"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo cd /d "%APPROOT%"
>> "%PREFIX%\CoCANoT-Diagnostics.bat" echo "%PREFIX%\python.exe" "%APPROOT%\react_dashboard.py" %%*
> "%PREFIX%\CoCANoT.vbs" echo Set cocanotShell = CreateObject("WScript.Shell")
>> "%PREFIX%\CoCANoT.vbs" echo cocanotShell.Run Chr(34) ^& "%PREFIX%\CoCANoT-Diagnostics.bat" ^& Chr(34), 0, False
if not exist "%PREFIX%\CoCANoT-Diagnostics.bat" (echo ERROR: Diagnostics launcher missing >> "%LOG%" & goto :fail)
if not exist "%PREFIX%\CoCANoT.vbs" (echo ERROR: Quiet launcher missing >> "%LOG%" & goto :fail)

rem Optional shortcuts must not prevent an otherwise healthy app installation.
set "STEP=create optional Windows shortcuts"
>> "%LOG%" echo Starting: %STEP%
if exist "%APPROOT%\windows_shortcuts.ps1" (
  "%POWERSHELL_EXE%" -NoProfile -STA -ExecutionPolicy Bypass -File "%APPROOT%\windows_shortcuts.ps1" -Prefix "%PREFIX%" > "%PREFIX%\shortcut-setup-output.log" 2>&1
  if errorlevel 1 (
    >> "%LOG%" echo WARNING: Shortcut creation failed; see shortcut-setup-output.log
  ) else (
    >> "%LOG%" echo Shortcut helper completed successfully.
  )
) else (
  >> "%LOG%" echo WARNING: Shortcut helper unavailable.
)
>> "%LOG%" echo SUCCESS: CoCANoT runtime installed.
echo CoCANoT installed. Launcher: "%PREFIX%\CoCANoT.vbs".
echo Installation log: "%LOG%"
echo MRI defacing Step 3C needs separately installed WSL2 Ubuntu.
exit /b 0

:fail
echo ERROR: CoCANoT post-install failed during "%STEP%".
echo Inspect installation log: "%LOG%"
>> "%LOG%" echo ERROR: Post-install failed during "%STEP%".
exit /b 1
