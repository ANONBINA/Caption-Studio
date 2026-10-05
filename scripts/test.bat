@echo off
REM test.bat - lint + test the project inside the project's venv.
REM
REM Usage:  scripts\test.bat          (pytest + ruff, as documented in the README)
REM         scripts\test.bat quick    (pytest only)

setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found - running setup --dev first...
    call scripts\setup.bat --dev
)

if "%~1"=="quick" (
    ".venv\Scripts\python.exe" -m pytest
    goto :eof
)
".venv\Scripts\python.exe" -m pytest
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m ruff check caption_studio tests
endlocal
