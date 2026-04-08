@echo off
setlocal enabledelayedexpansion

REM Handle UNC paths by mapping a temporary drive letter
pushd "%~dp0"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Could not navigate to script directory.
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
    pause
    exit /b 1
)

set "SCRIPT_DIR=%CD%"

echo ============================================
echo   BrainstormCompanion APK Builder
echo ============================================
echo.

REM Check if MAUI workload is installed
dotnet workload list 2>nul | findstr /i "maui" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] MAUI workload not found. Installing...
    echo     This may take several minutes on first run.
    echo.
    dotnet workload install maui-android
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo [ERROR] Failed to install MAUI workload.
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
        echo         Try running this script as Administrator.
        popd
        pause
        exit /b 1
    )
    echo.
    echo [OK] MAUI workload installed.
    echo.
)

REM Copy source to local temp folder to avoid slow network I/O during build
set "LOCAL_BUILD=%TEMP%\BrainstormAPKBuild"
echo [0/3] Copying source to local disk for faster build...
if exist "%LOCAL_BUILD%" rmdir /s /q "%LOCAL_BUILD%"
xcopy "%SCRIPT_DIR%\BrainstormCompanion" "%LOCAL_BUILD%\BrainstormCompanion\" /E /I /Q /Y >nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to copy source files locally.
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
    popd
    pause
    exit /b 1
)
echo   [OK] Source copied to %LOCAL_BUILD%
echo.

echo [1/3] Building APK (arm64)...
dotnet publish "%LOCAL_BUILD%\BrainstormCompanion\BrainstormCompanion.csproj" -f net8.0-android -c Release -p:AndroidSdkDirectory=C:\Android\Sdk -p:RuntimeIdentifiers=android-arm64
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed!
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
    echo.
    echo Common fixes:
    echo   - Install Android SDK via Visual Studio Installer
    echo   - Or set ANDROID_HOME environment variable
    echo   - Run: dotnet workload install maui-android
    rmdir /s /q "%LOCAL_BUILD%" 2>nul
    popd
    pause
    exit /b 1
)

echo.
echo [2/3] Locating APK...

set "APK_SIGNED="

for /r "%LOCAL_BUILD%\BrainstormCompanion\bin\Release\net8.0-android" %%f in (*-Signed.apk) do (
    set "APK_SIGNED=%%f"
)

if not defined APK_SIGNED (
    for /r "%LOCAL_BUILD%\BrainstormCompanion\bin\Release\net8.0-android" %%f in (*.apk) do (
        set "APK_SIGNED=%%f"
    )
)

if not defined APK_SIGNED (
    echo.
    echo [WARNING] APK file not found in build output.
    powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chord.wav').PlaySync()"
    rmdir /s /q "%LOCAL_BUILD%" 2>nul
    popd
    pause
    exit /b 1
)

echo [3/3] Copying APK back to project...
set "OUTPUT_DIR=%SCRIPT_DIR%\BrainstormCompanion\bin\Release\net8.0-android\publish"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
copy /Y "!APK_SIGNED!" "%OUTPUT_DIR%\" >nul

REM Get just the filename for display
for %%a in ("!APK_SIGNED!") do set "APK_NAME=%%~nxa"
set "FINAL_APK=%OUTPUT_DIR%\%APK_NAME%"

REM Cleanup local build
rmdir /s /q "%LOCAL_BUILD%" 2>nul

echo.
echo ============================================
echo   APK ready!
echo   %FINAL_APK%
echo ============================================
echo.
echo To install on your phone:
echo   1. Copy APK to phone via USB or network
echo   2. Enable "Install from unknown sources"
echo   3. Tap the APK to install
echo.
echo Or install via ADB:
echo   adb install "%FINAL_APK%"
echo.
powershell -c "(New-Object Media.SoundPlayer 'C:\Windows\Media\chimes.wav').PlaySync()"

popd
pause