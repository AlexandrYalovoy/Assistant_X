@echo off
rem Intake of the inbox folder of the workspace: double-click, or intake.bat --dry-run / --resume (assistant-x intake run).
rem Then Claude writes meta.jsonl, then assistant-x intake build and assistant-x intake apply (docs\INTAKE.md).
rem No pause when AX_NOPAUSE is set (background runs); the exit code is that of the intake.
call "%~dp0assistant-x.bat" intake run %*
set RC=%ERRORLEVEL%
echo.
if not defined AX_NOPAUSE pause
exit /b %RC%
