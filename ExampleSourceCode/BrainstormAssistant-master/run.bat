@echo off
if exist "%~dp0publish\BrainstormAssistant.exe" (
    start "" "%~dp0publish\BrainstormAssistant.exe"
) else (
    echo App not built yet. Run build.bat first.
    pause
)
