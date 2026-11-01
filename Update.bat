@echo off
rem Update Assistant X with a double click: the latest release with a tag of the project (assistant-x update --from,
rem setup/self_update.py), checked against its SHA256SUMS and installed beside the version in use; the library and its
rem settings stay as they are. Update.bat URL takes another page of the project (its GitFlic page, a fork).
chcp 65001 >nul
set PYTHONUTF8=1
set "AXM=%AX_MACHINE_DIR%"
if not defined AXM set "AXM=%USERPROFILE%\.assistant_x"
set "PY=%AXM%\venv\Scripts\python.exe"
if exist "%AXM%\python.txt" set /p PY=<"%AXM%\python.txt"
set "URL=%~1"
if not defined URL set "URL=https://github.com/AlexandrYalovoy/Assistant_X"
if not exist "%PY%" (
  echo Assistant X is not installed on this PC yet: double-click Setup.bat first.
  goto end
)
"%PY%" -m assistant_x.cli.main update --from "%URL%"
:end
echo.
if not defined AX_NOPAUSE pause
