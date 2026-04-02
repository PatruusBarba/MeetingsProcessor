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
- Global hotkey **Ctrl+Shift+R** to start/stop recording (optional in Settings; polled from the GUI thread so it stays stable with PyAudio)
- Single instance: starting again focuses the existing window
- Optional **offline live transcript** during recording (**faster-whisper**): enable in **Settings**; text appears in the main window (chunked, ~3 s latency)

### Live transcription

1. `pip install -r requirements.txt` (includes `faster-whisper`, `numpy`; first run downloads the chosen Whisper model).
2. **Settings** → enable **Live transcript**, pick **model** (e.g. `base` or `small`), **device** (`cpu` or `cuda`), **compute type** (`int8` on CPU, often `float16` on GPU).
3. Start recording; lines append as each audio chunk is decoded. This is **near real-time** (not word-by-word streaming).

## Tests

Pure-Python helpers (no WASAPI). From the repo root:

```powershell
$env:PYTHONPATH = "."
python -m unittest discover -s tests -p "test*.py" -v
```

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
- **Transcription**: If import fails, install `faster-whisper`. GPU needs a CUDA-capable PyTorch setup; otherwise use **cpu** + **int8**.

## License

Refer to dependency licenses (PyAudioWPatch, lameenc, pystray, Pillow) and your project policy.
