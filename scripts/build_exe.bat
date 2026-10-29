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
pause
exit /b 1

:python_found
echo Installing required packages and PyInstaller...
%PY_CMD% -m pip install -r "%ROOT%\requirements.txt" pyinstaller
if errorlevel 1 goto :install_error
for /f "delims=" %%D in ('%PY_CMD% -c "import customtkinter, pathlib; print(pathlib.Path(customtkinter.__file__).resolve().parent)"') do set "CTK_DIR=%%D"
if not defined CTK_DIR (
    echo Cannot locate the CustomTkinter package.
    pause
    exit /b 1
)
if not exist "%CTK_DIR%\assets\themes\dark-blue.json" (
    echo Required CustomTkinter theme dark-blue.json was not found.
    echo Reinstall customtkinter and try again.
    pause
    exit /b 1
)
if not exist "%ROOT%\build" mkdir "%ROOT%\build"
if not exist "%ROOT%\build\pyinstaller" mkdir "%ROOT%\build\pyinstaller"
if not exist "%ROOT%\dist" mkdir "%ROOT%\dist"
echo Building Sanistra.exe and bundling CustomTkinter assets...
echo Online update source is configured: yasikami/Sanistra.
if exist "%ROOT%\assets\icon.ico" (
    %PY_CMD% -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all customtkinter --collect-all mutagen --add-data "%CTK_DIR%\assets;customtkinter\assets" --icon "%ROOT%\assets\icon.ico" --name "Sanistra" --distpath "%ROOT%\dist" --workpath "%ROOT%\build\pyinstaller" --specpath "%ROOT%\build" "%ROOT%\src\player.py"
) else (
    %PY_CMD% -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all customtkinter --collect-all mutagen --add-data "%CTK_DIR%\assets;customtkinter\assets" --name "Sanistra" --distpath "%ROOT%\dist" --workpath "%ROOT%\build\pyinstaller" --specpath "%ROOT%\build" "%ROOT%\src\player.py"
)
if errorlevel 1 goto :build_error
if exist "%ROOT%\config\update_config.example.json" copy /Y "%ROOT%\config\update_config.example.json" "%ROOT%\dist\update_config.example.json" >nul
echo.
echo Build complete: dist\Sanistra.exe
echo Build artefacts are separated into build\ and dist\ folders.
pause
exit /b 0

:install_error
echo Package installation failed. Check your internet connection and Python installation.
pause
exit /b 1
:build_error
echo Build failed. Check the messages above.
pause
exit /b 1
