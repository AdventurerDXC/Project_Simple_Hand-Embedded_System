@echo off
chcp 65001 >nul
setlocal

if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
    if errorlevel 1 py -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
python main.py
pause
