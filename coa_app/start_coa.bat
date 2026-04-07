@echo off
chcp 65001 >nul
cd /d "%~dp0.."

:: Kill old instance if running
taskkill /f /im python.exe /fi "WINDOWTITLE eq LabCore*" >nul 2>&1

:: Start Flask app (minimized)
start /min "LabCore COA Server" python coa_app\app.py

:: Wait for server to start
timeout /t 3 /nobreak >nul

:: Open Chrome in app mode (no address bar)
where chrome >nul 2>&1
if %errorlevel% equ 0 (
    start "" chrome --app=http://localhost:5050
) else (
    where msedge >nul 2>&1
    if %errorlevel% equ 0 (
        start "" msedge --app=http://localhost:5050
    ) else (
        start http://localhost:5050
    )
)
