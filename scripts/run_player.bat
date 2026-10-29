@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
cd /d "%ROOT%"

where py >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py"
    goto :python_found
)
where python >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_found
)

echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
echo During setup, enable "Add Python to PATH".
pause
exit /b 1

:python_found
%PY_CMD% -c "import customtkinter, pygame, mutagen" >nul 2>&1
if errorlevel 1 (
    echo Installing missing dependencies for the first run...
    %PY_CMD% -m pip install -r "%ROOT%\requirements.txt"
    if errorlevel 1 goto :install_error
)
echo Starting Sanistra...
%PY_CMD% "%ROOT%\src\player.py"
if errorlevel 1 pause
exit /b 0

:install_error
echo Package installation failed. Check your internet connection and Python installation.
pause
exit /b 1
