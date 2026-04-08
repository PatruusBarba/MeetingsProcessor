@echo off
setlocal

set "SHARED=\\vmware-host\Shared Folders\vmw11SharedFolder\testP6\BrainstormAssistant\publish"

echo Building BrainstormAssistant...
dotnet build "%~dp0BrainstormAssistant\BrainstormAssistant.csproj" -c Release
if %ERRORLEVEL% NEQ 0 (
    echo Build failed!
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
    pause
    exit /b 1
)
echo.
echo Running tests...
dotnet test "%~dp0BrainstormAssistant.Tests\BrainstormAssistant.Tests.csproj" -c Release --verbosity normal
if %ERRORLEVEL% NEQ 0 (
    echo Tests failed!
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
    pause
    exit /b 1
)
echo.
echo Publishing...
dotnet publish "%~dp0BrainstormAssistant\BrainstormAssistant.csproj" -c Release -o "%~dp0publish" --self-contained false
if %ERRORLEVEL% NEQ 0 (
    echo Publish failed!
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
    pause
    exit /b 1
)
echo.
echo Build complete! Output in: %~dp0publish\

:: Copy to shared VM folder so the host can access the build
echo Copying to shared folder...
if not exist "%SHARED%" mkdir "%SHARED%"
robocopy "%~dp0publish" "%SHARED%" /MIR /NJH /NJS /NP /NFL /NDL
echo Copied to: %SHARED%
echo.
echo Run with: run.bat
powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chimes.wav').PlaySync()"
pause
