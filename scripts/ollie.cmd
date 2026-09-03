@echo off
rem scripts/ollie for Windows: build what changed and start, without the pull or the tests.
rem See START.bat for why there are no parenthesised blocks here.
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" goto :venv
where py >nul 2>&1
if not errorlevel 1 goto :launcher
where python >nul 2>&1
if not errorlevel 1 goto :onpath
echo no Python found; install Python 3.12 or later 1>&2
exit /b 1

:venv
".venv\Scripts\python.exe" "scripts\launch.py" --quick %*
exit /b %errorlevel%

:launcher
py -3 "scripts\launch.py" --quick %*
exit /b %errorlevel%

:onpath
python "scripts\launch.py" --quick %*
exit /b %errorlevel%
