@echo off
chcp 65001 >nul
title LabCore COA — Instalacja
echo.
echo  ╔══════════════════════════════════════╗
echo  ║     LabCore COA — Instalacja         ║
echo  ╚══════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] Python nie znaleziony!
    echo      Zainstaluj Python 3.10+ z python.org
    echo      Zaznacz "Add Python to PATH" podczas instalacji.
    pause
    exit /b 1
)
echo  [OK] Python znaleziony

:: Check git
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] Git nie znaleziony!
    echo      Zainstaluj Git z git-scm.com
    pause
    exit /b 1
)
echo  [OK] Git znaleziony

:: Check Microsoft Word
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Winword.exe" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Microsoft Word nie znaleziony!
    echo      Word jest wymagany do generowania PDF swiadectw.
    echo      Instalacja bedzie kontynuowana, ale swiadectwa nie beda dzialac.
    echo.
) else (
    echo  [OK] Microsoft Word znaleziony
)

:: Set install dir
set INSTALL_DIR=%USERPROFILE%\LabCore
echo.
echo  Instalacja do: %INSTALL_DIR%
echo.

:: Clone or pull repo
if exist "%INSTALL_DIR%\.git" (
    echo  [..] Aktualizacja repozytorium...
    cd /d "%INSTALL_DIR%"
    git pull origin main
) else (
    echo  [..] Pobieranie repozytorium...
    git clone https://github.com/karol-t-baker/lims.git "%INSTALL_DIR%"
)
if %errorlevel% neq 0 (
    echo  [X] Blad pobierania repozytorium!
    pause
    exit /b 1
)
echo  [OK] Repozytorium pobrane

:: Install Python dependencies
echo  [..] Instalacja zaleznosci Python...
cd /d "%INSTALL_DIR%"
pip install flask docxtpl docx2pdf requests bcrypt --quiet
if %errorlevel% neq 0 (
    echo  [X] Blad instalacji zaleznosci!
    pause
    exit /b 1
)
echo  [OK] Zaleznosci zainstalowane

:: Create data directory
if not exist "%INSTALL_DIR%\coa_app\data" mkdir "%INSTALL_DIR%\coa_app\data"

:: Create desktop shortcut
echo  [..] Tworzenie skrotu na pulpicie...
(
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo sLinkFile = oWS.SpecialFolders^("Desktop"^) ^& "\LabCore COA.lnk"
echo Set oLink = oWS.CreateShortcut^(sLinkFile^)
echo oLink.TargetPath = "%INSTALL_DIR%\coa_app\START.bat"
echo oLink.WorkingDirectory = "%INSTALL_DIR%\coa_app"
echo oLink.Description = "LabCore COA — Swiadectwa jakosci"
echo oLink.WindowStyle = 7
echo oLink.Save
) > "%TEMP%\create_shortcut.vbs"
cscript /nologo "%TEMP%\create_shortcut.vbs"
del "%TEMP%\create_shortcut.vbs"
echo  [OK] Skrot "LabCore COA" na pulpicie

:: Create START.bat in coa_app — launches server + browser in app mode
(
echo @echo off
echo title LabCore COA
echo cd /d "%INSTALL_DIR%\coa_app"
echo set LABCORE_NO_BROWSER=1
echo start /min "" python app.py
echo timeout /t 3 /noexec ^>nul
echo start "" msedge --app=http://localhost:5050 --window-size=1280,900 2^>nul ^|^| start "" chrome --app=http://localhost:5050 --window-size=1280,900 2^>nul ^|^| start http://localhost:5050
) > "%INSTALL_DIR%\coa_app\START.bat"

:: Create UPDATE.bat for easy updates
(
echo @echo off
echo title LabCore COA — Aktualizacja
echo cd /d "%INSTALL_DIR%"
echo git pull origin main
echo pip install -r coa_app\requirements.txt --quiet
echo echo.
echo echo  Zaktualizowano. Uruchom LabCore COA ponownie.
echo pause
) > "%INSTALL_DIR%\coa_app\UPDATE.bat"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║     Instalacja zakonczona!           ║
echo  ╠══════════════════════════════════════╣
echo  ║                                      ║
echo  ║  Skrot na pulpicie: LabCore COA      ║
echo  ║  Kliknij dwukrotnie aby uruchomic.   ║
echo  ║                                      ║
echo  ║  Aktualizacja: UPDATE.bat            ║
echo  ║                                      ║
echo  ╚══════════════════════════════════════╝
echo.
echo  Uruchomic teraz? (T/N)
set /p RUN="> "
if /i "%RUN%"=="T" (
    start "" "%INSTALL_DIR%\coa_app\START.bat"
)
