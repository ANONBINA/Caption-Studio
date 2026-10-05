@echo off
REM serve.bat — launch the Caption Studio web app.
REM Re-runs setup automatically if .venv is missing.
REM
REM Usage:
REM   scripts\serve.bat            Desktop mode - http://127.0.0.1:8000 (loopback only)
REM   scripts\serve.bat --lan      Mobile mode  - binds LAN + prints a QR code for your phone
REM   scripts\serve.bat 192.168.1.50 [port]   Bind an explicit host (also mobile mode)
REM
REM Mobile mode:
REM   . Detects this PC's LAN IP automatically (scripts\lan_ip.py)
REM   . Adds it to CAPTION_STUDIO_ALLOWED_HOSTS so the app accepts the Host header
REM   . Reminds you about the Windows Firewall prompt (must click Allow)
REM
REM NOTE: cmd quirk — never put unescaped parentheses in echo text inside a
REM parenthesized block; a ")" there terminates the block early.

setlocal enabledelayedexpansion
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found - running setup first...
    call scripts\setup.bat
)

set "MODE=desktop"
set "HOST=127.0.0.1"
if "%~1"=="--lan" (
    set "MODE=lan"
    set "HOST=0.0.0.0"
) else if not "%~1"=="" (
    REM Explicit host argument also enables mobile mode, mirroring serve.sh
    set "MODE=lan"
    set "HOST=%~1"
)
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8000"

if "!MODE!"=="lan" (
    set "LAN_IP="
    for /f "usebackq delims=" %%i in (`".venv\Scripts\python.exe" scripts\lan_ip.py 2^>nul`) do set "LAN_IP=%%i"

    if defined LAN_IP (
        set "CAPTION_STUDIO_ALLOWED_HOSTS=!LAN_IP!"
        echo.
        echo   [MOBILE] Open on your phone - same Wi-Fi:
        echo     http://!LAN_IP!:!PORT!
        ".venv\Scripts\python.exe" scripts\print_qr.py "http://!LAN_IP!:!PORT!" 2>nul
        if errorlevel 1 echo     QR not available - type the URL above instead
        echo.
        echo   [*] Every device on this network can read/change the library - no login.
        echo   [*] If Windows Firewall asks, click ALLOW for Python/private networks.
        echo   [*] Phone must be on the same Wi-Fi - not guest or mobile hotspot.
        echo.
    ) else (
        echo [*] Could not auto-detect your LAN IP. Find it with ipconfig and set:
        echo     set CAPTION_STUDIO_ALLOWED_HOSTS=192.168.1.50
    )
)

echo Caption Studio -^> http://!HOST!:!PORT!  -  Ctrl+C to stop
".venv\Scripts\python.exe" -m uvicorn caption_studio.app:create_app --factory --host !HOST! --port !PORT!
endlocal
