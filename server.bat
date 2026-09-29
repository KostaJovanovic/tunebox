@echo off
rem Runs only this module in the emulator; ..\server.bat has the options (--silent, --lan, --port).
call "%~dp0..\server.bat" music %*
