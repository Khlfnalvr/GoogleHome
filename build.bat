@echo off
rem Builds dist\GoogleHomeWidget.exe (needs Python 3.11+), and
rem dist\GoogleHomeWidget-Setup.exe if Inno Setup 6 is installed.
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
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto no_installer
"%ISCC%" /Q installer.iss || exit /b 1
echo Built dist\GoogleHomeWidget-Setup.exe
exit /b 0
:no_installer
echo Inno Setup 6 not found (https://jrsoftware.org/isdl.php), skipped the installer.
