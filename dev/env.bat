@echo off
rem Makes sure .venv exists and has everything in dev\requirements.txt, then sets
rem %PY% to its python. Called by server.bat and save.bat (call devenv.bat);
rem start.bat uses the same .venv.
rem
rem The requirement files are hashed into .venv\requirements.sha, so pip only runs
rem when one of them changed since the last install, not on every start.

set "PY=%~dp0..\.venv\Scripts\python.exe"
set PYTHONUTF8=1
if exist "%PY%" goto deps

echo [env]   creating .venv (first run)
py -3.13 -m venv "%~dp0..\.venv" 2>nul
if errorlevel 1 python -m venv "%~dp0..\.venv"
if not exist "%PY%" (
  echo [err]   could not create .venv - install Python 3.13 from python.org, then run this again
  exit /b 1
)

:deps
"%PY%" "%~dp0ensure_deps.py"
if errorlevel 1 (
  echo [err]   installing the Python packages failed - see above
  exit /b 1
)
exit /b 0
