# Meeting Audio Recorder

Windows desktop app that records your **microphone** and **system audio** (WASAPI loopback) together into a single **mono MP3** file. See [SPEC.md](SPEC.md) for the full technical specification.

## Requirements

- Windows 10 (build 1903+) or later, 64-bit
- Python 3.10+

## Quick start (PowerShell)

```powershell
cd <path-to-cloned-repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

On first run, settings are stored in `settings.json` next to the executable (or next to `main.py` when running from source). Recordings default to a `recordings` folder in the same directory unless you change it in **Settings**.

## Features (summary)

- WASAPI microphone + speaker loopback capture, mixed to mono
- Pause / resume (one file per session)
- Live timer and level meters
- MP3 export via **lameenc** (128 kbps mono); intermediate WAV is removed after encoding
- System tray (minimize on close optional), tray menu for show / record / stop / quit
- Global hotkey **Ctrl+Shift+R** to start/stop recording (optional in Settings)
- Single instance: starting again focuses the existing window

## Build a standalone folder (PyInstaller)

```powershell
pip install pyinstaller
pyinstaller --onedir --windowed --name MeetingRecorder --icon=assets\icon.ico main.py
```

Output: `dist\MeetingRecorder\` with `MeetingRecorder.exe` and dependencies.

## Troubleshooting

- **No microphone / privacy**: Windows **Settings → Privacy → Microphone** — allow access for desktop apps.
- **PyAudioWPatch**: Wheels are **Windows-only**. Install fails on Linux or macOS by design.
- **Devices**: Use **Refresh** if you plug in USB audio gear after launch.

## License

Refer to dependency licenses (PyAudioWPatch, lameenc, pystray, Pillow) and your project policy.
