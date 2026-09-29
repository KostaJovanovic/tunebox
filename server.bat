@echo off
setlocal
cd /d "%~dp0"

rem Runs Tunebox on this PC the way ele serves it (under /music/), for working on it.
rem dev\emulate.py has the details. Opens the browser when it is up.
rem
rem   server.bat                http://localhost:8000/music/, through this PC's speakers
rem   server.bat --silent       without sound (fake player)
rem   server.bat --lan          also reachable from phones on the LAN
rem   server.bat --port 9000    another port
rem
rem Local data lives in dev\data; save.bat, option 6, copies ele's real data there.
rem To just use Tunebox on this PC, start.bat is simpler.

call dev\env.bat || goto fail
"%PY%" dev\emulate.py %*
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
pause
exit /b 1
