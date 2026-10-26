@echo off
rem Debug report: double-click, then pass on the file it creates (the workspace's .assistant_x\debug).
call "%~dp0..\assistant-x.bat" debug-report %*
set RC=%ERRORLEVEL%
echo.
if not defined AX_NOPAUSE pause
exit /b %RC%
