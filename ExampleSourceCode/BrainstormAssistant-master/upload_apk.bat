@echo off
setlocal enabledelayedexpansion

REM Handle UNC paths
pushd "%~dp0"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Could not navigate to script directory.
    pause
    exit /b 1
)

echo ============================================
echo   Upload APK to FTP
echo ============================================
echo.

set "APK_DIR=%CD%\BrainstormCompanion\bin\Release\net8.0-android\publish"
set "APK_FILE="

for %%f in ("%APK_DIR%\*-Signed.apk") do (
    set "APK_FILE=%%f"
)

if not defined APK_FILE (
    for %%f in ("%APK_DIR%\*.apk") do (
        set "APK_FILE=%%f"
    )
)

if not defined APK_FILE (
    echo [ERROR] No APK found in:
    echo   %APK_DIR%
    echo.
    echo Run build_apk.bat first.
    popd
    pause
    exit /b 1
)

for %%a in ("!APK_FILE!") do set "APK_NAME=%%~nxa"
echo   Found: %APK_NAME%
echo   Uploading to ftp://192.168.3.2:3721/ ...
echo.

curl -T "!APK_FILE!" "ftp://anonymous:anonymous@192.168.3.2:3721/%APK_NAME%" --ftp-pasv --progress-bar
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] FTP upload failed.
    echo   Check that ftp://192.168.3.2:3721/ is reachable.
    popd
    pause
    exit /b 1
)

echo.
echo ============================================
echo   [OK] APK uploaded!
echo   %APK_NAME% -^> ftp://192.168.3.2:3721/
echo ============================================
echo.

popd
pause