@echo off
rem Installation of Assistant X: double-click. Python, the packages (from the medium without internet), the program,
rem the models and the programs into %USERPROFILE%\.assistant_x (AX_MACHINE_DIR: another folder), the connection
rem to Claude. The workspace is AX_WORKSPACE, else Documents\Assistant X. Setup.bat --base PACKAGE installs a base
rem package right after.
chcp 65001 >nul
set PYTHONUTF8=1
set "APPDIR=%~dp0"
rem a medium (prepare-media --out): the program in app\, its packages in packages\
if exist "%~dp0app\assistant_x\" set "APPDIR=%~dp0app\"
if exist "%~dp0app\assistant_x\" set "AX_MEDIUM=%~dp0"
cd /d "%APPDIR%"
set "AXM=%AX_MACHINE_DIR%"
if not defined AXM set "AXM=%USERPROFILE%\.assistant_x"
set "WS=%AX_WORKSPACE%"
if not defined WS set "WS=%USERPROFILE%\Documents\Assistant X"
set "PACKS=%WS%\.assistant_x\packages"
if exist "%~dp0packages\" set "PACKS=%~dp0packages"
set "PYVER=3.11"
set "PYCHECK=sys.version_info >= (3, 11)"
if exist "%PACKS%\python_version.txt" (
  set /p PYVER=<"%PACKS%\python_version.txt"
)
if exist "%PACKS%\python_version.txt" call :exact
set "PYTAG=%PYVER:.=%"
set "PY="
call :try "%APPDIR%.venv\Scripts\python.exe"
if not defined PY call :try "%AXM%\venv\Scripts\python.exe"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python%PYTAG%\python.exe"
if not defined PY call :try "%AXM%\Python%PYTAG%\python.exe"
if not defined PY call :try "%ProgramFiles%\Python%PYTAG%\python.exe"
if not defined PY for /f "delims=" %%i in ('py -%PYVER% -c "import sys; print(sys.executable)" 2^>nul') do call :try "%%i"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY call :try "%%i"
if not defined PY call :install_python
if not defined PY (
  echo.
  echo Python %PYVER% was not found and could not be installed.
  echo Install Python %PYVER% by hand from python.org or send a screenshot of this window.
  goto end
)
"%PY%" -m assistant_x.setup.install %*
:end
echo.
if not defined AX_NOPAUSE pause
exit /b

:exact
set "PYCHECK=sys.version_info[:2] == (%PYVER:.=,%)"
exit /b

:try
if exist "%~1" "%~1" -c "import sys; sys.exit(0 if %PYCHECK% else 1)" >nul 2>nul && set "PY=%~1"
exit /b

:install_python
set "PYEXE="
for %%f in ("%PACKS%\python-%PYVER%*-amd64.exe") do set "PYEXE=%%~f"
if not defined PYEXE exit /b
rem the installer runs only when its sha256 is the one prepare-media wrote (SHA256SUMS.txt beside it)
for %%f in ("%PYEXE%") do set "PYNAME=%%~nxf"
set "WANT="
set "GOT="
if exist "%PACKS%\SHA256SUMS.txt" for /f "usebackq tokens=1,2" %%a in ("%PACKS%\SHA256SUMS.txt") do if /i "%%b"=="*%PYNAME%" set "WANT=%%a"
for /f "skip=1 delims=" %%h in ('certutil -hashfile "%PYEXE%" SHA256') do if not defined GOT set "GOT=%%h"
if defined GOT set "GOT=%GOT: =%"
if not defined WANT (
  echo %PYNAME% is not named in %PACKS%\SHA256SUMS.txt: it is not run. Install Python %PYVER% by hand from python.org.
  set "PYEXE="
  exit /b
)
if /i not "%GOT%"=="%WANT%" (
  echo %PYNAME% is not the file the medium was made with ^(another sha256^): it is not run.
  set "PYEXE="
  exit /b
)
echo Python %PYVER% not found: installing it from the media for the current user only, this takes a couple of minutes...
"%PYEXE%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0 AssociateFiles=0 TargetDir="%AXM%\Python%PYTAG%"
call :try "%AXM%\Python%PYTAG%\python.exe"
exit /b
