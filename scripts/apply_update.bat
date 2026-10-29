@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
cd /d "%ROOT%"
if not exist "%~dp0update_patch.zip" (
    echo No update_patch.zip found next to this script.
    echo Place the patch ZIP in the scripts folder and name it update_patch.zip.
    pause
    exit /b 1
)
echo Close Sanistra before applying an update.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=(Get-Location).Path; $zip=Join-Path $root 'scripts\update_patch.zip'; $tmp=Join-Path $env:TEMP ('SanistraPatch_'+[guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null; try { Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force; Copy-Item -Path (Join-Path $tmp '*') -Destination $root -Recurse -Force; Remove-Item -LiteralPath $zip -Force; Write-Host 'Patch applied successfully.' -ForegroundColor Green } finally { if (Test-Path $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force } }"
if errorlevel 1 (
    echo Update failed. Make sure the app is closed and the patch archive is valid.
    pause
    exit /b 1
)
echo Update complete. You can start Sanistra again.
pause
