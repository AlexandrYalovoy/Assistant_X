@echo off
rem Installation of the intake: LibreOffice, Tesseract (rus+eng), 7-Zip; paths in assistant_x.local.toml.
call "%~dp0..\assistant-x.bat" setup-intake %*
set RC=%ERRORLEVEL%
echo.
if not defined AX_NOPAUSE pause
exit /b %RC%
