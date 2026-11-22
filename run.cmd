@echo off
rem Runs scripts\run.py with the installed Python. Works from any folder, even when "python" is not on PATH.
setlocal
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0scripts\run.py" %*
