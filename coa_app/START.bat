@echo off
echo === LabCore COA ===
echo Otwieranie przegladarki na http://localhost:5050
echo Nie zamykaj tego okna.
echo.
cd /d "%~dp0"
python app.py
pause
