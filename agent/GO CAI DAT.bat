@echo off
rem  Go may dong bo WMS: bo tu chay khi bat may + dung chuong trinh dang chay
chcp 65001 >nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\May dong bo WMS.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\May dong bo WMS.cmd" 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'wms_agent\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
taskkill /fi "WINDOWTITLE eq May dong bo WMS*" >nul 2>nul
echo Da go may dong bo WMS tren may nay.
pause
