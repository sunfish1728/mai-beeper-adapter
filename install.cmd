@echo off
setlocal
title Mai Beeper Adapter Installer

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"

echo.
if not "%INSTALL_RESULT%"=="0" echo Installation failed. Please send a screenshot of this window.
echo Press any key to close this window...
pause >nul
exit /b %INSTALL_RESULT%
