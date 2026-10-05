@echo off
REM setup.bat - one-shot environment setup for Caption Studio (Windows).
REM Idempotent: safe to re-run; it only performs the steps that are still missing.
REM
REM Usage:  scripts\setup.bat
REM         scripts\setup.bat --dev       (also install pytest/ruff/httpx)
REM         scripts\setup.bat --qrcode    (also install qrcode - QR for phone access)

setlocal enabledelayedexpansion
cd /d "%~dp0.."

set "WITH_DEV=0"
set "WITH_QR=0"
:parseargs
if "%~1"=="--dev" set "WITH_DEV=1"
if "%~1"=="--qrcode" set "WITH_QR=1"
shift
if not "%~1"=="" goto parseargs

echo.
echo ==^> Checking prerequisites
where py >nul 2>nul
if not errorlevel 1 (
    set "PYLAUNCHER=py"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo   [X] Python not found. Install Python 3.10+ from https://python.org
        exit /b 1
    )
    set "PYLAUNCHER=python"
)
%PYLAUNCHER% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo   [X] Python 3.10+ required.
    exit /b 1
)
echo   [OK] Python found

echo.
echo ==^> Virtual environment (.venv)
if exist ".venv\Scripts\python.exe" (
    echo   [OK] already exists
) else (
    %PYLAUNCHER% -m venv .venv
    if errorlevel 1 (
        echo   [X] Failed to create .venv
        exit /b 1
    )
    echo   [OK] created .venv
)

echo.
echo ==^> Installing the app (editable, with web deps)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
if "%WITH_DEV%"=="1" (
    ".venv\Scripts\python.exe" -m pip install --quiet -e ".[web,dev]"
    if errorlevel 1 exit /b 1
    echo   [OK] installed .[web,dev] (pytest + ruff included)
) else (
    ".venv\Scripts\python.exe" -m pip install --quiet -e ".[web]"
    if errorlevel 1 exit /b 1
    echo   [OK] installed .[web]
)
if "%WITH_DEV%"=="0" echo   [!] pass --dev to also install pytest/ruff

echo.
echo ==^> QR code support (for phone access)
".venv\Scripts\python.exe" -c "import qrcode" >nul 2>nul
if not errorlevel 1 (
    echo   [OK] qrcode already installed
) else if "%WITH_QR%"=="1" (
    ".venv\Scripts\python.exe" -m pip install --quiet qrcode
    if errorlevel 1 exit /b 1
    echo   [OK] installed qrcode
) else (
    echo   [!] not installed - run with --qrcode to get a scannable QR for your phone
)

echo.
echo ==^> Config file (config.json)
if exist "config.json" (
    echo   [OK] already exists - left untouched (it holds your TMDB key / merge rules)
) else (
    copy /y config.example.json config.json >nul
    echo   [OK] created from config.example.json
)

echo.
echo ==^> Data directory
if not exist "data" mkdir data
dir /b data\*.csv >nul 2>nul
if not errorlevel 1 (
    echo   [OK] catalog CSV(s) found in data\
) else (
    echo   [!] no catalog CSV in data\ yet - drop one there or use Import CSV in the UI
)

echo.
echo ==^> Verifying
".venv\Scripts\python.exe" -c "import caption_studio; print('caption-studio import OK')"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m caption_studio.cli stats

echo.
echo ==^> Done
echo   Start the web app:  scripts\serve.bat      (http://127.0.0.1:8000)
echo   Mobile/phone mode:  scripts\serve.bat --lan  (QR + LAN URL)
echo   Run the tests:      scripts\test.bat
echo   Set a TMDB key:     Settings -^> TMDB in the UI, or set TMDB_API_KEY
endlocal
