@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Git + ele helper for Tunebox, the same as homeapps' save.bat.
rem
rem   save.bat            menu
rem   save.bat save       commit + push to GitHub, then deploy to ele if it is reachable
rem   save.bat commit     commit only
rem   save.bat deploy     upload what changed in Tunebox to ele (no git)
rem   save.bat status     show what differs from ele, change nothing
rem   save.bat pull       git pull
rem   save.bat pull-data  copy ele's live data into dev\data for server.bat
rem
rem Deploying asks for the SSH user and password each time and stores neither.
rem Only app code goes to ele (dev\deploy.py lists it); the systemd unit is
rem compared and reported, never installed.

set "COMMIT_ONLY=0"
set "SAVE_ERROR=0"
set "ACTION=%~1"
call :resolvebranch

if /i "%ACTION%"=="save"      goto checkrepo
if /i "%ACTION%"=="commit"    (set "COMMIT_ONLY=1" & goto checkrepo)
if /i "%ACTION%"=="deploy"    goto deploy
if /i "%ACTION%"=="status"    goto status
if /i "%ACTION%"=="pull"      goto pull
if /i "%ACTION%"=="pull-data" goto pulldata

:menu
echo.
echo === tunebox ===
echo.
echo   1  commit      add + commit, no push
echo   2  save        add + commit + push to GitHub, then deploy to ele if it is reachable
echo   3  deploy      upload what changed to ele (no git)
echo   4  status      what differs from ele (changes nothing)
echo   5  pull        git pull
echo   6  pull data   copy ele's live data into dev\data for server.bat
echo   7  quit
echo.
set "CHOICE="
set /p CHOICE=select [1-7]:
if "%CHOICE%"=="1" (set "COMMIT_ONLY=1" & goto checkrepo)
if "%CHOICE%"=="2" goto checkrepo
if "%CHOICE%"=="3" goto deploy
if "%CHOICE%"=="4" goto status
if "%CHOICE%"=="5" goto pull
if "%CHOICE%"=="6" goto pulldata
if "%CHOICE%"=="7" exit /b 0
echo [err]  invalid choice
goto menu


:checkrepo
if exist ".git" goto save
echo.
echo [warn] no git repository here yet
set "DOINIT="
set /p DOINIT=run "git init" now? (y/n):
if /i not "%DOINIT%"=="y" (
  echo [git]  skipped - nothing to commit into
  set "SAVE_ERROR=1"
  goto end
)
git init -b main
if errorlevel 1 (
  echo [err]  git init failed
  set "SAVE_ERROR=1"
  goto end
)
call :resolvebranch
goto save


:save
echo.
echo === git: save ===
echo.

rem An unfinished merge must never reach "git add ." - it would stage the
rem conflict markers and record the conflict as settled.
set "UNMERGED="
for /f "delims=" %%u in ('git diff --name-only --diff-filter=U 2^>nul') do set "UNMERGED=1"
if defined UNMERGED (
  echo [err]  unresolved merge conflicts - resolve these first:
  git diff --name-only --diff-filter=U
  set "SAVE_ERROR=1"
  goto end
)

echo [git]  stage
git add .
git diff --cached --quiet
if not errorlevel 1 (
  echo [git]  nothing new to commit
  goto aftercommit
)
git status --short

echo.
rem The message never goes through a command line: with delayed expansion on,
rem `git commit -m "%MSG%"` would lose every "!" in it. PowerShell writes it to
rem a UTF-8 file from the environment and git reads the file.
for /f "delims=" %%d in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"') do set "NOW=%%d"
set "DEFMSG=update %NOW%"
set "MSG="
set /p "MSG=commit message [%DEFMSG%]: "
if not defined MSG set "MSG=%DEFMSG%"
set "MSGFILE=%TEMP%\tunebox-save-message.txt"
powershell -NoProfile -Command "[IO.File]::WriteAllText($env:MSGFILE, $env:MSG)"
git commit -F "%MSGFILE%"
if errorlevel 1 (
  del "%MSGFILE%" >nul 2>nul
  echo [err]  git commit failed
  set "SAVE_ERROR=1"
  goto end
)
del "%MSGFILE%" >nul 2>nul
call :resolvebranch

:aftercommit
if "%COMMIT_ONLY%"=="1" (
  echo.
  echo [git]  committed locally, not pushed
  goto end
)

rem GitHub. No remote is the normal state until the repository is made.
if "%REMOTE%"=="" (
  echo.
  echo [git]  no GitHub remote yet - nothing pushed. Add one later with:
  echo        git remote add origin https://github.com/KostaJovanovic/tunebox.git
  goto maybedeploy
)
if "%BRANCH%"=="" (
  echo [err]  no branch checked out ^(detached HEAD?^) - not pushing
  set "SAVE_ERROR=1"
  goto maybedeploy
)
echo.
git push -u %REMOTE% %BRANCH%
if not errorlevel 1 (
  echo [git]  pushed %REMOTE%/%BRANCH%
  goto maybedeploy
)
rem A push can fail for reasons a pull cannot fix (auth, no network). Ask the
rem remote which one this is before suggesting anything.
git ls-remote %REMOTE% >nul 2>nul
if errorlevel 1 (
  echo [err]  push failed - cannot reach or authenticate to %REMOTE%. The commit is saved locally.
) else (
  echo [warn] push rejected - %REMOTE%/%BRANCH% has commits you don't. Run option 5 ^(pull^), then save again.
)
set "SAVE_ERROR=1"

:maybedeploy
echo.
call dev\env.bat || (set "SAVE_ERROR=1" & goto end)
"%PY%" dev\deploy.py check >nul
if errorlevel 1 (
  echo [ele]  ele is not on this network - not deployed ^(run "save.bat deploy" when you are home^)
  goto end
)
echo [ele]  ele is reachable - deploying
"%PY%" dev\deploy.py deploy
if errorlevel 1 set "SAVE_ERROR=1"
goto end


:deploy
echo.
echo === ele: deploy ===
echo.
call dev\env.bat || (set "SAVE_ERROR=1" & goto end)
"%PY%" dev\deploy.py deploy
if errorlevel 1 set "SAVE_ERROR=1"
goto end

:status
echo.
echo === ele: status ===
echo.
call dev\env.bat || (set "SAVE_ERROR=1" & goto end)
"%PY%" dev\deploy.py status
if errorlevel 1 set "SAVE_ERROR=1"
goto end

:pulldata
echo.
echo === ele: pull data ===
echo.
call dev\env.bat || (set "SAVE_ERROR=1" & goto end)
"%PY%" dev\deploy.py pull-data
if errorlevel 1 set "SAVE_ERROR=1"
goto end

:pull
echo.
echo === git: pull ===
echo.
if "%BRANCH%"=="" (echo [err]  no branch checked out & set "SAVE_ERROR=1" & goto end)
if "%REMOTE%"=="" (echo [err]  no remote configured yet & set "SAVE_ERROR=1" & goto end)
git pull %REMOTE% %BRANCH%
if errorlevel 1 set "SAVE_ERROR=1"
goto end


rem The checked-out branch into %BRANCH% (empty with no repo or a detached HEAD),
rem and the remote to use into %REMOTE%: the branch's upstream, else origin, else
rem the first remote. Empty when there is none.
:resolvebranch
set "BRANCH="
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
if /i "%BRANCH%"=="HEAD" set "BRANCH="
set "REMOTE="
if not "%BRANCH%"=="" for /f "delims=" %%r in ('git config branch.%BRANCH%.remote 2^>nul') do set "REMOTE=%%r"
if not "%REMOTE%"=="" exit /b 0
git remote get-url origin >nul 2>nul
if not errorlevel 1 (set "REMOTE=origin" & exit /b 0)
for /f "delims=" %%r in ('git remote 2^>nul') do if "!REMOTE!"=="" set "REMOTE=%%r"
exit /b 0


:end
echo.
pause
exit /b %SAVE_ERROR%
