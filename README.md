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
- Optional **offline live transcript** during recording: **Parakeet TDT V3 INT8 ONNX** via **ONNX Runtime** (~650 MB on disk — same layout as [smcleod/parakeet-tdt-0.6b-v3-int8](https://huggingface.co/smcleod/parakeet-tdt-0.6b-v3-int8)); no NeMo, no 2.5 GB `.nemo` download

### Live transcription (ONNX Parakeet)

1. Download or copy a folder containing **`nemo128.onnx`**, **`encoder-model.int8.onnx`**, **`decoder_joint-model.int8.onnx`**, **`vocab.txt`** (your BrainstormAssistant `parakeet-tdt-0.6b-v3` folder matches).
2. `pip install -r requirements.txt` (includes **`onnxruntime`**). For NVIDIA GPU: `pip install onnxruntime-gpu` and set **Inference device** to **cuda** in Settings.
3. **Settings** → enable transcript → **Browse** to that folder → optional **UI refresh** interval (seconds) for how often the full transcript is recomputed on growing audio.
4. The panel shows the **current full hypothesis** text (TDT greedy decode, same rule set as `nano-parakeet`). All local.

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
- **Transcription**: Needs a valid **ONNX model folder** and `onnxruntime` (or `onnxruntime-gpu`). If you pick **cuda** but ORT has no CUDA provider, the app falls back to CPU.

## License

Refer to dependency licenses (PyAudioWPatch, lameenc, pystray, Pillow) and your project policy.
