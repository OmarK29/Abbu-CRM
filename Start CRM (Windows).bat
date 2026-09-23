@echo off
rem Double-click to start Simple CRM on Windows.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto install
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
if not defined PY goto nopython
echo First run: setting up the app (about a minute)...
%PY% -m venv .venv || goto failed

:install
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto failed
echo Starting Simple CRM... (close this window to stop it)
".venv\Scripts\python.exe" -m streamlit run app.py
pause
exit /b 0

:nopython
echo Python 3.10 or newer is required.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again.
pause
exit /b 1

:failed
echo Setup failed. Check your internet connection and try again.
pause
exit /b 1
