@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "INSTALL_EXIT=%ERRORLEVEL%"
echo.
if not "%INSTALL_EXIT%"=="0" (
  echo Installation failed. Keep the messages above for troubleshooting.
)
pause
exit /b %INSTALL_EXIT%
