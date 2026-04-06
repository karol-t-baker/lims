@echo off
echo === LabCore COA - Instalacja ===
echo.

pip install flask docxtpl docx2pdf requests
if %errorlevel% neq 0 (
    echo BLAD: pip install nie powiodl sie
    pause
    exit /b 1
)

echo.
echo Instalacja zakonczona.
echo Uruchom: START.bat
pause
