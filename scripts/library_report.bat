@echo off
rem State of the library: what to verify, replace or improve (the report goes to .assistant_x\debug).
call "%~dp0..\assistant-x.bat" report %*
set RC=%ERRORLEVEL%
echo.
if not defined AX_NOPAUSE pause
exit /b %RC%
