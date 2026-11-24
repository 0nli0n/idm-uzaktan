@echo off
chcp 65001 >nul
rem Telefonun bilgisayara ulasabilmesi icin Windows Guvenlik Duvari'nda
rem yalnizca OZEL (ev) aglar icin 8765/TCP ve 8766/UDP portlarini acar.

net session >nul 2>&1
if not %errorlevel%==0 (
    echo Yonetici izni isteniyor...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

netsh advfirewall firewall delete rule name="IDM Uzaktan (TCP)" >nul 2>&1
netsh advfirewall firewall delete rule name="IDM Uzaktan (UDP)" >nul 2>&1
netsh advfirewall firewall add rule name="IDM Uzaktan (TCP)" dir=in action=allow protocol=TCP localport=8765 profile=private
netsh advfirewall firewall add rule name="IDM Uzaktan (UDP)" dir=in action=allow protocol=UDP localport=8766 profile=private

echo.
echo  Tamam. Guvenlik duvari kurallari eklendi (yalnizca ozel aglar).
echo  Not: Wi-Fi aginizin Windows'ta "Ozel ag" olarak ayarli olmasi gerekir.
echo  (Ayarlar ^> Ag ve Internet ^> Wi-Fi ^> agin adi ^> Ag profili: Ozel)
echo.
pause
