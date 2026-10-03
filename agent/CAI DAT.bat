@echo off
rem ==================================================================
rem  CAI DAT MAY DONG BO WMS
rem  - Tao moi truong Python + cai thu vien
rem  - Tu chay khi bat may (them vao Startup)
rem  - Chay ngay
rem ==================================================================
chcp 65001 >nul
cd /d "%~dp0"
title Cai dat may dong bo WMS

echo.
echo  [1/4] Kiem tra Python...
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
    echo.
    echo  CHUA CAI PYTHON.
    echo  Trang tai Python se mo ra. Khi cai nho TICH o "Add python.exe to PATH".
    echo  Cai xong, chay lai file "CAI DAT.bat" nay.
    start "" https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
%PY% --version

echo.
echo  [2/4] Tao moi truong Python va cai thu vien (lan dau mat 1-2 phut)...
set "VENV=%LOCALAPPDATA%\dinh-vi-pa\venv"
if not exist "%VENV%\Scripts\python.exe" %PY% -m venv "%VENV%"
"%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo  LOI khi cai thu vien - kiem tra ket noi mang roi chay lai.
    pause
    exit /b 1
)

echo.
echo  [3/4] Kiem tra ket noi App + Google Sheet + WMS...
"%VENV%\Scripts\python.exe" wms_agent.py --check
if errorlevel 1 (
    echo.
    echo  LOI ket noi - xem dong LOI phia tren. Chup man hinh gui nguoi ho tro.
    pause
    exit /b 1
)

echo  [4/4] Cai tu chay khi bat may...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTBAT=%~sdp0run_wms_agent.bat"
del "%STARTUP%\May dong bo WMS.lnk" 2>nul
> "%STARTUP%\May dong bo WMS.cmd" echo @echo off
>>"%STARTUP%\May dong bo WMS.cmd" echo start "May dong bo WMS" /min "%SHORTBAT%"

start "May dong bo WMS" /min "%~dp0run_wms_agent.bat"

echo.
echo  ==============================================================
echo   CAI DAT XONG. May dong bo dang chay (cua so thu nho o thanh Taskbar).
echo   - Tu chay moi khi bat may.
echo   - KHONG tat cua so "May dong bo WMS".
echo   - Vao app, tab WMS se hien "May dong bo ...: dang chay".
echo  ==============================================================
pause
