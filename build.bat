@echo off
setlocal

cd /d "%~dp0"

echo === Creating virtual environment ===
if not exist .venv (
    python -m venv .venv
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

echo === Building MeetingRecorder ===
pyinstaller --noconfirm --onedir --windowed --name MeetingRecorder --icon=assets\icon.ico --additional-hooks-dir=hooks main.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

echo === Build complete: dist\MeetingRecorder\ ===
