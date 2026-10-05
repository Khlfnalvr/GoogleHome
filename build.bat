@echo off
rem Builds dist\GoogleHomeWidget.exe (needs Python 3.11+).
rem Put client_secret.json next to this file to bundle it into the .exe,
rem so users only have to click "Sign in with Google".
cd /d "%~dp0"
if not exist .venv python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt pyinstaller || exit /b 1
set EXTRA=
if exist client_secret.json set EXTRA=--add-data "client_secret.json;."
pyinstaller --noconfirm --onefile --windowed --name GoogleHomeWidget --collect-data customtkinter %EXTRA% src\widget.py || exit /b 1
echo.
echo Built dist\GoogleHomeWidget.exe
