@echo off
setlocal

set "PYTHON=C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe"

cd /d "%~dp0"

echo === Creating virtual environment ===
if not exist .venv (
    "%PYTHON%" -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create venv.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

echo === Installing dependencies ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install requirements.
    exit /b 1
)

python -m pip install pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install PyInstaller.
    exit /b 1
)

REM webrtcvad-wheels provides the webrtcvad module but registers metadata
REM under a different name. Create a shim so PyInstaller's hook finds it.
set "METADIR=.venv\Lib\site-packages\webrtcvad-2.0.10.dist-info"
if not exist "%METADIR%" (
    mkdir "%METADIR%"
    echo Metadata-Version: 2.1> "%METADIR%\METADATA"
    echo Name: webrtcvad>> "%METADIR%\METADATA"
    echo Version: 2.0.10>> "%METADIR%\METADATA"
    echo.> "%METADIR%\RECORD"
    echo pip> "%METADIR%\INSTALLER"
)

echo === Building MeetingRecorder ===
pyinstaller --noconfirm --onedir --windowed --name MeetingRecorder --icon=assets\icon.ico main.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

echo === Build complete: dist\MeetingRecorder\ ===
