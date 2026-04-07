@echo off
chcp 65001 >nul
echo ============================================
echo   LabCore COA — Instalacja
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [BLAD] Python nie znaleziony.
    echo Pobierz Python 3.12+: https://www.python.org/downloads/
    echo WAZNE: Zaznacz "Add Python to PATH" przy instalacji!
    echo.
    pause
    exit /b 1
)
echo [OK] Python znaleziony

:: Check LibreOffice
if exist "C:\Program Files\LibreOffice\program\soffice.exe" (
    echo [OK] LibreOffice znaleziony
) else if exist "C:\Program Files (x86)\LibreOffice\program\soffice.exe" (
    echo [OK] LibreOffice znaleziony
) else (
    echo [BLAD] LibreOffice nie znaleziony.
    echo Pobierz LibreOffice: https://www.libreoffice.org/download/
    echo.
    pause
    exit /b 1
)

:: Install dependencies
echo.
echo Instalacja zaleznosci...
pip install flask docxtpl requests bcrypt urllib3 >nul 2>&1
if %errorlevel% neq 0 (
    echo [BLAD] Nie udalo sie zainstalowac zaleznosci.
    pause
    exit /b 1
)
echo [OK] Zaleznosci zainstalowane

:: Create desktop shortcut
echo.
echo Tworzenie skrotu na pulpicie...
set SCRIPT_DIR=%~dp0
set DESKTOP=%USERPROFILE%\Desktop

:: Create the launcher bat
echo @echo off > "%SCRIPT_DIR%start_coa.bat"
echo chcp 65001 ^>nul >> "%SCRIPT_DIR%start_coa.bat"
echo cd /d "%SCRIPT_DIR%.." >> "%SCRIPT_DIR%start_coa.bat"
echo start /min "" python coa_app\app.py >> "%SCRIPT_DIR%start_coa.bat"
echo timeout /t 3 /nobreak ^>nul >> "%SCRIPT_DIR%start_coa.bat"
echo start "" chrome --app=http://localhost:5050 >> "%SCRIPT_DIR%start_coa.bat"

:: Create VBS to make a shortcut (Windows doesn't have mklink for .lnk easily)
echo Set ws = CreateObject("WScript.Shell") > "%TEMP%\make_shortcut.vbs"
echo Set sc = ws.CreateShortcut("%DESKTOP%\LabCore COA.lnk") >> "%TEMP%\make_shortcut.vbs"
echo sc.TargetPath = "%SCRIPT_DIR%start_coa.bat" >> "%TEMP%\make_shortcut.vbs"
echo sc.WorkingDirectory = "%SCRIPT_DIR%" >> "%TEMP%\make_shortcut.vbs"
echo sc.WindowStyle = 7 >> "%TEMP%\make_shortcut.vbs"
echo sc.Description = "LabCore COA - Swiadectwa jakosci" >> "%TEMP%\make_shortcut.vbs"
echo sc.Save >> "%TEMP%\make_shortcut.vbs"
cscript //nologo "%TEMP%\make_shortcut.vbs"
del "%TEMP%\make_shortcut.vbs"

echo [OK] Skrot "LabCore COA" utworzony na pulpicie
echo.
echo ============================================
echo   Instalacja zakonczona!
echo   Kliknij "LabCore COA" na pulpicie.
echo ============================================
echo.
pause
