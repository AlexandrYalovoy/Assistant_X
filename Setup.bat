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
rem the installer of python.org for a PC without Python and without a medium (a git checkout): its last 3.11 build
rem with an installer (setup/prepare_media.py LAST_INSTALLER), run only when signed by the Python Software Foundation
set "PYFULL=3.11.9"
set "PYCHECK=sys.version_info >= (3, 11)"
set "RC=0"
set "DRY="
set "YES=%AX_YES%"
set "NOPAUSE=%AX_NOPAUSE%"
for %%a in (%*) do (
  if /i "%%~a"=="--dry-run" set "DRY=1"
  if /i "%%~a"=="--yes" set "YES=1"
  if /i "%%~a"=="--yes" set "NOPAUSE=1"
  if /i "%%~a"=="--json" set "NOPAUSE=1"
  if /i "%%~a"=="--background" set "NOPAUSE=1"
  if /i "%%~a"=="--status" set "NOPAUSE=1"
)
if exist "%PACKS%\python_version.txt" (
  set /p PYVER=<"%PACKS%\python_version.txt"
)
if exist "%PACKS%\python_version.txt" call :exact
set "PYTAG=%PYVER:.=%"
set "PY="
rem every Python that is here already first (no winget: its installer fails on some PCs), then the installer of the
rem medium, then the one of python.org; AX_PYTHON_SOURCE tells the installation (and its JSON) which one it took
call :try "%APPDIR%.venv\Scripts\python.exe" "the environment of this folder"
if not defined PY call :try "%AXM%\venv\Scripts\python.exe" "the environment of an earlier installation"
if not defined PY call :try "%LOCALAPPDATA%\Programs\Python\Python%PYTAG%\python.exe" "Python %PYVER% installed for the user"
if not defined PY call :try "%AXM%\Python%PYTAG%\python.exe" "Python %PYVER% an earlier Setup.bat installed"
if not defined PY call :try "%ProgramFiles%\Python%PYTAG%\python.exe" "Python %PYVER% installed for every user"
if not defined PY for /f "delims=" %%i in ('py -%PYVER% -c "import sys; print(sys.executable)" 2^>nul') do call :try "%%i" "Python %PYVER% of the py launcher"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY call :try "%%i" "a Python on the PATH"
if not defined PY call :install_python
if not defined PY if not exist "%PACKS%\python-*.exe" call :download_python
if not defined PY (
  echo.
  echo Python %PYVER% was not found and could not be installed.
  echo Install Python %PYVER% by hand from python.org or send a screenshot of this window.
  set "RC=1"
  goto end
)
set "AX_PYTHON_SOURCE=%PYSRC%: %PY%"
"%PY%" -m assistant_x.setup.install %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo The installation did not finish ^(code %RC%^): the reason is in the messages above.
  echo Run Setup.bat once more after fixing it, or send a screenshot of this window.
)
:end
echo.
if not defined NOPAUSE pause
exit /b %RC%

:exact
set "PYCHECK=sys.version_info[:2] == (%PYVER:.=,%)"
exit /b

:try
if exist "%~1" "%~1" -c "import sys; sys.exit(0 if %PYCHECK% else 1)" >nul 2>nul && set "PY=%~1" && set "PYSRC=%~2"
exit /b

:install_python
set "PYEXE="
for %%f in ("%PACKS%\python-%PYVER%*-amd64.exe") do if exist "%%~f" set "PYEXE=%%~f"
rem a pattern that matched nothing can stay in the variable as it is: only a file that is there counts
if defined PYEXE if not exist "%PYEXE%" set "PYEXE="
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
call :try "%AXM%\Python%PYTAG%\python.exe" "Python %PYVER% installed now from the medium, for the user only"
exit /b

:download_python
rem no medium (a git checkout): the installer of python.org, with the user's yes, run only when its Authenticode
rem signature is valid and names the Python Software Foundation
set "PYURL=https://www.python.org/ftp/python/%PYFULL%/python-%PYFULL%-amd64.exe"
set "PYEXE=%TEMP%\python-%PYFULL%-amd64.exe"
echo Python %PYVER% is not installed on this PC. Setup.bat can download it from python.org ^(about 25 MB^):
echo   %PYURL%
if defined DRY (
  echo ^(trial run: nothing is downloaded^)
  set "PYEXE="
  exit /b
)
if not defined YES (
  set "ANS="
  set /p "ANS=Download and install it for the current user only? [Y/n] "
)
if not defined YES if /i "%ANS%"=="n" (
  set "PYEXE="
  exit /b
)
powershell -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri $env:PYURL -OutFile ($env:PYEXE + '.part')" || (
  echo The download from python.org failed: install Python %PYVER% by hand from python.org.
  del /q "%PYEXE%.part" 2>nul
  set "PYEXE="
  exit /b
)
powershell -NoProfile -NonInteractive -Command "$s = Get-AuthenticodeSignature -LiteralPath ($env:PYEXE + '.part'); if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Python Software Foundation') { Write-Output ('signature ' + $s.Status + ' of ' + $s.SignerCertificate.Subject); exit 1 }" || (
  echo The downloaded file is not signed by the Python Software Foundation: it is not run and is deleted.
  del /q "%PYEXE%.part" 2>nul
  set "PYEXE="
  exit /b
)
move /y "%PYEXE%.part" "%PYEXE%" >nul
echo Installing Python %PYFULL% for the current user only, this takes a couple of minutes...
"%PYEXE%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0 AssociateFiles=0 TargetDir="%AXM%\Python%PYTAG%"
del /q "%PYEXE%" 2>nul
set "PYEXE="
call :try "%AXM%\Python%PYTAG%\python.exe" "Python %PYFULL% installed now from python.org, for the user only, its signature checked"
exit /b
