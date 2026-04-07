@echo off
chcp 65001 >nul
title LabCore COA — Build
echo.
echo  ╔══════════════════════════════════════╗
echo  ║     LabCore COA — Build              ║
echo  ╚══════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] Python nie znaleziony!
    pause
    exit /b 1
)
echo  [OK] Python znaleziony

:: Install PyInstaller if needed
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo  [..] Instalacja PyInstaller...
    pip install pyinstaller --quiet
)
echo  [OK] PyInstaller dostepny

:: Install app dependencies
echo  [..] Instalacja zaleznosci...
pip install flask docxtpl requests bcrypt num2words --quiet
echo  [OK] Zaleznosci zainstalowane

:: Build
echo.
echo  [..] Budowanie aplikacji...
cd /d "%~dp0"
pyinstaller labcore_coa.spec --noconfirm
if %errorlevel% neq 0 (
    echo  [X] Build nie powiodl sie!
    pause
    exit /b 1
)

:: Create data directory in output
mkdir dist\LabCore_COA\data 2>nul

:: Copy icon next to exe
copy labcore.ico dist\LabCore_COA\ >nul 2>&1

echo.
echo  ╔══════════════════════════════════════╗
echo  ║     Build ukonczony!                 ║
echo  ╠══════════════════════════════════════╣
echo  ║                                      ║
echo  ║  Wynik: coa_app\dist\LabCore_COA\    ║
echo  ║  Uruchom: LabCore_COA.exe            ║
echo  ║                                      ║
echo  ╚══════════════════════════════════════╝
echo.
pause
