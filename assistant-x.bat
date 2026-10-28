@echo off
rem Assistant X from the command line: assistant-x.bat <command> [arguments] (assistant-x.bat help lists them).
rem The Python environment is .venv beside this file (Setup.bat makes it), else %USERPROFILE%\.assistant_x\venv (or
rem the %LOCALAPPDATA%\AssistantX\venv of an install before 0.5.1).
rem No pause; the exit code is that of the command.
chcp 65001 >nul
set PYTHONUTF8=1
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\.assistant_x\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\AssistantX\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo No Python environment of Assistant X: run Setup.bat first
  exit /b 1
)
pushd "%~dp0"
"%PY%" -m assistant_x %*
set RC=%ERRORLEVEL%
popd
exit /b %RC%
