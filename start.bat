@echo off
setlocal
cd /d "%~dp0"

rem Tunebox on this PC: it plays through this PC's speakers, and the browser is the remote.
rem
rem   start.bat           http://localhost:8888/, and phones and other computers on the network can use it too
rem   start.bat --local   this PC only
rem   start.bat --port 9000
rem
rem The first start sets everything up in this folder (Python packages, mpv, Node): a few minutes.
rem Needs Python 3.11 or newer from python.org. Close this window to stop Tunebox.

set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto deps
echo [tunebox] setting up (first start only)
py -3 -m venv "%~dp0.venv" 2>nul
if not exist "%PY%" python -m venv "%~dp0.venv"
if not exist "%PY%" (
  echo [tunebox] Python is missing: install Python 3.11 or newer from python.org ^(tick "Add to PATH"^), then start this again
  goto fail
)

:deps
rem the packages are installed again only when requirements.txt changed
fc /b "%~dp0requirements.txt" "%~dp0.venv\requirements.txt" >nul 2>&1 && goto run
echo [tunebox] installing Python packages
"%PY%" -m pip install --quiet --disable-pip-version-check -r "%~dp0requirements.txt" || goto fail
copy /y "%~dp0requirements.txt" "%~dp0.venv\requirements.txt" >nul

:run
"%PY%" "%~dp0run.py" %*
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
pause
exit /b 1
