@echo off
setlocal
cd /d "%~dp0"
echo Jarvis source beta - Windows 11, Python 3.11 required.
echo This installs Python packages from PyPI into this folder's .venv.
echo No administrator access is required. Each tester needs their own API key.
pause
py -3.11 --version
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -e ".[gui,voice,vision,documents,files,browser]"
if errorlevel 1 goto failed
echo Setup complete. Run Start-Jarvis.cmd.
pause
exit /b 0
:failed
echo Setup failed. Read the error above. Do not disable Windows security.
pause
exit /b 1
