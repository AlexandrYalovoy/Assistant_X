@echo off
rem Install a base package of Assistant X with a double click (the program installed by Setup.bat first): the .axbase
rem file beside this file (or in its base\ folder), else the Windows dialog "Open a file" asks for one; the plan of the
rem installation, one confirmation, then the count of documents installed. Install-Base.bat PACKAGE takes that file.
chcp 65001 >nul
set PYTHONUTF8=1
set "AXM=%AX_MACHINE_DIR%"
if not defined AXM set "AXM=%USERPROFILE%\.assistant_x"
set "PY=%AXM%\venv\Scripts\python.exe"
if exist "%AXM%\python.txt" set /p PY=<"%AXM%\python.txt"
if not exist "%PY%" (
  echo Assistant X is not installed on this PC yet: double-click Setup.bat first.
  goto end
)
"%PY%" -m assistant_x.setup.base_pick --folder "%~dp0." %*
:end
echo.
if not defined AX_NOPAUSE pause
