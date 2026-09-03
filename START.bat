@echo off
rem
rem Double-click this file on Windows. It pulls the latest main, rebuilds whatever needs
rem rebuilding, checks nothing is broken, and starts Ollie.
rem
rem The procedure itself lives in scripts\launch.py, which START.command also runs on macOS
rem and Linux. Only the four lines that find a Python differ between the two.
rem
rem No parenthesised blocks below, deliberately. cmd.exe expands %errorlevel% when it parses
rem a block rather than when it runs, so `if exist x ( run & exit /b %errorlevel% )` returns
rem the code from before the command ever ran. Labels sidestep it entirely.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :venv
where py >nul 2>&1
if not errorlevel 1 goto :launcher
where python >nul 2>&1
if not errorlevel 1 goto :onpath
goto :nopython

:venv
".venv\Scripts\python.exe" "scripts\launch.py" %*
exit /b %errorlevel%

:launcher
py -3 "scripts\launch.py" %*
exit /b %errorlevel%

:onpath
python "scripts\launch.py" %*
exit /b %errorlevel%

:nopython
echo.
echo   No Python found.
echo.
echo   Install Python 3.12 or later from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup, then run this again.
echo.
pause
exit /b 1
