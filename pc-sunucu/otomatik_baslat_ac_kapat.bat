@echo off
chcp 65001 >nul
rem Sunucuyu Windows acilisinda arka planda (penceresiz) baslatir.
rem Tekrar calistirirsaniz otomatik baslatmayi kapatir.

set "KISAYOL=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\IDM Uzaktan.lnk"

if exist "%KISAYOL%" (
    del "%KISAYOL%"
    echo.
    echo  Otomatik baslatma KAPATILDI.
    echo.
    pause
    exit /b
)

set "HEDEF="
set "ARG="
for /f "delims=" %%i in ('where pyw 2^>nul') do if not defined HEDEF (
    set "HEDEF=%%i"
    set "ARG=-3 "
)
if not defined HEDEF for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined HEDEF set "HEDEF=%%i"
if not defined HEDEF (
    echo  Python bulunamadi. Once Python 3 kurun.
    pause
    exit /b
)

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:KISAYOL); $s.TargetPath=$env:HEDEF; $s.Arguments=$env:ARG + '\"%~dp0idm_uzaktan_sunucu.py\"'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"

echo.
echo  Otomatik baslatma ACILDI.
echo  Sunucu bundan sonra Windows acildiginda arka planda calisacak.
echo  PIN'inizi config.json dosyasinda gorebilirsiniz.
echo  Simdi baslatmak icin bilgisayari yeniden baslatin ya da baslat.bat'i calistirin.
echo.
pause
