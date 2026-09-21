@echo off
rem ==================================================================
rem  May dong bo WMS - chay nen tren may tinh o Viet Nam.
rem  Lan dau: tu tao moi truong Python va cai thu vien.
rem  Tu khoi dong lai neu bi loi / mat mang.
rem ==================================================================
chcp 65001 >nul
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\dinh-vi-pa\venv"

if not exist "%VENV%\Scripts\python.exe" (
    echo Dang tao moi truong Python lan dau...
    py -3 -m venv "%VENV%" || python -m venv "%VENV%"
    "%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip
    "%VENV%\Scripts\python.exe" -m pip install -q -r requirements.txt
)

:loop
"%VENV%\Scripts\python.exe" wms_agent.py
echo May dong bo dung - khoi dong lai sau 30 giay...
timeout /t 30 /nobreak >nul
goto loop
