@echo off
setlocal

cd /d "%~dp0"

set "SHARE=\\vmware-host\Shared Folders\vmw11SharedFolder\MeetingsProcessor"

echo === Running build ===
call build.bat
if errorlevel 1 (
    echo ERROR: Build failed, aborting share.
    exit /b 1
)

echo === Copying to shared folder ===
if exist "%SHARE%" rmdir /s /q "%SHARE%"
xcopy /e /i /y "dist\MeetingRecorder" "%SHARE%"
if errorlevel 1 (
    echo ERROR: Failed to copy to shared folder.
    exit /b 1
)

echo === Done: build copied to %SHARE% ===
