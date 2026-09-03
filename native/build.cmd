@echo off
rem Shim for cmd.exe and for double-clicking. See build.sh for why the logic is in build.py.
setlocal
cd /d "%~dp0"
where py >nul 2>&1 && (py build.py %* & exit /b %errorlevel%)
where python >nul 2>&1 && (python build.py %* & exit /b %errorlevel%)
echo no python found; install Python 3.12 or later 1>&2
exit /b 1
