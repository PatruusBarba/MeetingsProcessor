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
- Optional **offline streaming transcript** during recording (**NVIDIA Parakeet TDT V3** via **NeMo**): same algorithm as NVIDIA’s `speech_to_text_streaming_infer_rnnt.py`; strong **Russian** among 25 EU languages

### Live transcription (Parakeet V3)

1. Install PyTorch for your platform, then `pip install -r requirements.txt` (pulls **`nemo_toolkit[asr]`**, a large dependency set). First inference downloads **`nvidia/parakeet-tdt-0.6b-v3`** (~2.5 GB) from Hugging Face.
2. **Settings** → enable **streaming transcript**, set **device** (`cuda` strongly recommended), **torch dtype** (`float16` or `bfloat16` on GPU). Optional: tune chunk / left / right context (defaults match NeMo’s streaming example: 2 s / 10 s / 2 s).
3. Start recording; the text panel shows the **running hypothesis** (updated as NeMo’s streaming decoder advances). No cloud — all local.

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
- **Transcription**: Requires `nemo_toolkit[asr]` and a working **PyTorch** install. GPU + CUDA is recommended for Parakeet (~0.6B). CPU works but can be slow.

## License

Refer to dependency licenses (PyAudioWPatch, lameenc, pystray, Pillow) and your project policy.
