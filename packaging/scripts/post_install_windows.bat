@echo off
setlocal

set "COCANOT_PREFIX=%PREFIX%"
set "LAUNCHER_DIR=%COCANOT_PREFIX%\launchers"

if not exist "%LAUNCHER_DIR%" mkdir "%LAUNCHER_DIR%"

REM ------------------------------------------------------------
REM Imaging launcher
REM ------------------------------------------------------------

(
echo @echo off
echo set "PREFIX=%COCANOT_PREFIX%"
echo set "PATH=%%PREFIX%%\Library\bin;%%PREFIX%%\Scripts;%%PREFIX%%\bin;%%PATH%%"
echo set "PYTHONPATH=%%PREFIX%%\app;%%PYTHONPATH%%"
echo "%%PREFIX%%\python.exe" "%%PREFIX%%\app\ImagingPipeline\dashboard.py"
) > "%LAUNCHER_DIR%\cocanot-imaging.cmd"


REM ------------------------------------------------------------
REM Electrophysiology launcher
REM ------------------------------------------------------------

(
echo @echo off
echo set "PREFIX=%COCANOT_PREFIX%"
echo set "PATH=%%PREFIX%%\Library\bin;%%PREFIX%%\Scripts;%%PREFIX%%\bin;%%PATH%%"
echo set "PYTHONPATH=%%PREFIX%%\app;%%PYTHONPATH%%"
echo "%%PREFIX%%\python.exe" "%%PREFIX%%\app\ElectrophysiologyPipeline\dashboard.py"
) > "%LAUNCHER_DIR%\cocanot-electrophysiology.cmd"


REM ------------------------------------------------------------
REM Start Menu shortcuts
REM ------------------------------------------------------------

set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\CoCANoT"

if not exist "%STARTMENU%" mkdir "%STARTMENU%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%STARTMENU%\CoCANoT Imaging.lnk'); ^
   $s.TargetPath = '%LAUNCHER_DIR%\cocanot-imaging.cmd'; ^
   $s.WorkingDirectory = '%COCANOT_PREFIX%'; ^
   $s.Save()"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%STARTMENU%\CoCANoT Electrophysiology.lnk'); ^
   $s.TargetPath = '%LAUNCHER_DIR%\cocanot-electrophysiology.cmd'; ^
   $s.WorkingDirectory = '%COCANOT_PREFIX%'; ^
   $s.Save()"

exit /b 0