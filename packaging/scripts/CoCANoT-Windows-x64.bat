@echo off
setlocal EnableExtensions
title CoCANoT Windows x64 Setup
echo ============================================================
echo  CoCANoT Windows x64 Setup - WSL is a MANUAL prerequisite
echo ============================================================
echo.
echo BEFORE CONTINUING, install WSL 2 and Ubuntu 24.04 LTS yourself.
echo Open PowerShell as Administrator and run:
echo   wsl --install -d Ubuntu-24.04
echo Restart Windows if asked. Open Ubuntu once to create a Linux user.
echo Verify Ubuntu uses WSL version 2 with: wsl --list --verbose
echo Official instructions: https://learn.microsoft.com/windows/wsl/install
echo.
echo This installer will NOT install, enable or update WSL or Ubuntu.
echo After checking WSL, it downloads CoCANoT and its other dependencies.
echo An internet connection is required. Installation is for Windows x64.
echo.
choice /C YN /M "Have you already installed and initialized WSL 2 with Ubuntu 24.04 LTS"
if errorlevel 2 exit /b 1
set "COCANOT_REVISION=__GITHUB_SHA__"
set "COCANOT_SETUP=%TEMP%\CoCANoT-Windows-Setup-%RANDOM%.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/andreaarfn/CoCANoT-Pipelines/%COCANOT_REVISION%/packaging/scripts/install_windows_bat.ps1' -OutFile '%COCANOT_SETUP%'"
if errorlevel 1 (
 echo ERROR: Could not download the CoCANoT installer script.
 pause
 exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%COCANOT_SETUP%" -Revision "%COCANOT_REVISION%"
set "RESULT=%ERRORLEVEL%"
del /q "%COCANOT_SETUP%" >nul 2>nul
if not "%RESULT%"=="0" echo Installation failed. Read the error details above.
pause
exit /b %RESULT%
