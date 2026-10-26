@echo off
rem Prepare the media: on the build PC with internet, downloads the packages and the Python installer.
call "%~dp0..\assistant-x.bat" prepare-media %*
set RC=%ERRORLEVEL%
echo.
if not defined AX_NOPAUSE pause
exit /b %RC%
