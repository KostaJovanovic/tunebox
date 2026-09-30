@echo off
rem Tunebox from the command line: tunebox status, tunebox add SONG, tunebox -h  (tunebox\cli.py).
rem
rem It talks to the Tunebox running on this PC (start.bat, port 8888), or to another one:
rem   tunebox --server http://ele.local/music/ status
rem   tunebox server add home http://ele.local/music/     remembers it as the default
rem
rem Any Python 3.11 or newer runs it; the one start.bat set up in .venv is used when it is there.
setlocal
set PY="%~dp0.venv\Scripts\python.exe"
if not exist %PY% set PY=py -3
%PY% "%~dp0tunebox\cli.py" %*
exit /b %errorlevel%
