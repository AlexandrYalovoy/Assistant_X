@echo off
rem Review of the journal of queries: what was asked and where the search answered weakly.
call "%~dp0..\assistant-x.bat" query-log %*
set RC=%ERRORLEVEL%
echo.
if not defined AX_NOPAUSE pause
exit /b %RC%
