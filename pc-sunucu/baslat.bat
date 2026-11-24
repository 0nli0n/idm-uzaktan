@echo off
chcp 65001 >nul
title IDM Uzaktan Sunucusu
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 "%~dp0idm_uzaktan_sunucu.py"
    goto :son
)
where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0idm_uzaktan_sunucu.py"
    goto :son
)

echo.
echo  Python bulunamadi!
echo  https://www.python.org/downloads/ adresinden Python 3 kurun.
echo  Kurulumda "Add python.exe to PATH" kutusunu isaretlemeyi unutmayin.
echo.

:son
pause
