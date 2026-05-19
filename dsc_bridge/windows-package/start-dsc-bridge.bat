@echo off
REM Launches the DSC Bridge agent. Keep this window open while signing.

set INSTALL_DIR=%LOCALAPPDATA%\dsc-bridge

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%INSTALL_DIR%\dsc-bridge.json" copy "%~dp0dsc-bridge.json" "%INSTALL_DIR%\dsc-bridge.json" >nul

echo Starting DSC Bridge...
echo Config: %INSTALL_DIR%\dsc-bridge.json
echo Listening on https://127.0.0.1:4645
echo.
echo DO NOT close this window while signing. Press Ctrl+C to stop.
echo.

"%~dp0dsc-bridge.exe"
pause
