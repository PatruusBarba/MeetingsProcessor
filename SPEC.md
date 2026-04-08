# Meeting Audio Recorder — Technical Specification

## 1. Overview

A desktop Windows 10 application that records meeting audio from **any** conferencing app (Zoom, Teams, Google Meet, Discord, etc.) by simultaneously capturing:

- **Microphone input** — the user's own voice from a selected recording device.
- **System audio output (loopback)** — other participants' voices via WASAPI loopback capture from a selected playback device.

Both streams are mixed down into a single **mono** audio track (both voices in one channel, like a normal call recording). During recording, the intermediate format is WAV. After recording stops, the WAV is converted to MP3 and deleted.

---

## 2. Target Platform

| Parameter       | Value                              |
|-----------------|------------------------------------|
| OS              | Windows 10 (build 1903+)          |
| Architecture    | x86-64                             |
| Runtime         | Python 3.10+                       |
| GUI framework   | tkinter (stdlib)                   |
| Audio backend   | WASAPI (via `PyAudioWPatch`)       |
| Installer       | PyInstaller single-folder bundle   |

---

## 3. Technology Stack

| Component            | Library / Tool        | Why                                                                 |
|----------------------|-----------------------|---------------------------------------------------------------------|
| GUI                  | tkinter (stdlib)      | Built into Python, no extra install, simple and sufficient          |
| Audio capture        | PyAudioWPatch ≥ 0.2.12 | Fork of PyAudio that exposes WASAPI loopback mode natively        |
| Audio file I/O       | `wave` (stdlib)       | Writing raw PCM to WAV as intermediate format                       |
| MP3 export           | `lameenc`             | Pure-Python LAME encoder, converts WAV→MP3 without external tools   |
| Device enumeration   | PyAudioWPatch         | Lists input & output devices with WASAPI-specific properties        |
| System tray          | `pystray` + `Pillow`  | System tray icon support independent of GUI framework               |
| Config persistence   | `json` (stdlib)       | Save last-used devices, output folder, preferences                  |

---

## 4. Functional Requirements

### 4.1 Device Selection

| ID    | Requirement |
|-------|-------------|
| DS-1  | On startup, enumerate all active WASAPI audio **input** (microphone) devices and display them in a dropdown. |
| DS-2  | On startup, enumerate all active WASAPI audio **output** (playback/speaker) devices and display them in a second dropdown. The selected output device is used for loopback capture (recording what others say). |
| DS-3  | A **Refresh** button re-enumerates devices without restarting the app (handles USB devices plugged in after launch). |
| DS-4  | The app persists the last selected input and output device IDs. On next launch, pre-select them if they are still available. |
| DS-5  | Show device name and sample rate next to each entry, e.g. `Microphone (Realtek) — 48000 Hz`. |
| DS-6  | If a selected device becomes unavailable mid-recording, stop the recording gracefully, save what was captured, and display an error notification. |

### 4.2 Recording

| ID    | Requirement |
|-------|-------------|
| REC-1 | A single **Record** button starts simultaneous capture of the selected mic input and the selected output (loopback). |
| REC-2 | A **Stop** button ends both captures and writes the final file. |
| REC-3 | A **Pause / Resume** toggle suspends writing audio data to the buffer without closing streams. Paused time is excluded from the displayed duration. |
| REC-4 | During recording, display a live elapsed timer in `HH:MM:SS` format. |
| REC-5 | During recording, show real-time **VU level meters** (simple bar widgets) for both mic and system audio so the user can verify signal is present. |
| REC-6 | Recording parameters: 16-bit PCM, sample rate matching the device's default (typically 44100 or 48000 Hz). If mic and loopback have different sample rates, resample the lower one to match the higher one. |
| REC-7 | The two streams are mixed into a single **mono WAV** (sample-by-sample average of mic and loopback). The result sounds like a normal phone/meeting recording with all participants in one track. |
| REC-8 | Hotkey **Ctrl+Shift+R** toggles recording start/stop globally (even when the app window is not focused). |

### 4.3 File Output

| ID    | Requirement |
|-------|-------------|
| FO-1  | Default output directory: `./recordings/` (subfolder next to the exe). User can change this in Settings. |
| FO-2  | File naming pattern: `Meeting_YYYY-MM-DD_HH-MM-SS.mp3` (timestamp of recording start). |
| FO-3  | After stop, display the full path of the saved file in the status bar with a clickable link that opens the containing folder. |
| FO-4  | After recording stops, the engine converts the intermediate mono WAV to MP3 (128 kbps mono) using `lameenc`, then deletes the WAV. No external tools required. |

### 4.4 Settings (persisted as JSON)

| Setting                  | Type    | Default                                  |
|--------------------------|---------|------------------------------------------|
| Output directory         | string  | `./recordings/` (next to exe)            |
| Minimize to tray on close| bool    | `true`                                   |
| Start minimized          | bool    | `false`                                  |
| Global hotkey enabled    | bool    | `true`                                   |
| Last input device ID     | int     | `null`                                   |
| Last output device ID    | int     | `null`                                   |

### 4.5 System Tray

| ID    | Requirement |
|-------|-------------|
| ST-1  | When the user clicks the window close button (X) and "Minimize to tray on close" is enabled, the app hides to the system tray instead of exiting. |
| ST-2  | Tray icon context menu: **Show Window**, **Start Recording**, **Stop Recording**, **Quit**. |
| ST-3  | Tray icon changes colour/state to indicate: Idle (grey), Recording (red), Paused (yellow). |

---

## 5. Non-Functional Requirements

| ID     | Requirement |
|--------|-------------|
| NFR-1  | Audio capture must introduce no more than 20 ms additional latency. |
| NFR-2  | CPU usage during recording must stay below 5% on a modern quad-core CPU. |
| NFR-3  | The app must handle recordings up to 4 hours without memory issues (stream to disk, do not buffer in RAM). |
| NFR-4  | Graceful handling of permission errors (e.g. microphone access denied by Windows privacy settings) — show a clear message directing the user to Settings > Privacy > Microphone. |
| NFR-5  | No admin privileges required to run. |
| NFR-6  | Single-instance enforcement: if the app is already running, bring the existing window to front instead of launching a second instance. |

---

## 6. GUI Layout

```
┌──────────────────────────────────────────────────────────┐
│  Meeting Audio Recorder                          [—][□][X]│
├──────────────────────────────────────────────────────────┤
│                                                          │
│  🎤 Microphone          [▾ Dropdown list ............]  [⟳] │
│     Level: ████████░░░░░░░░░░░░                          │
│                                                          │
│  🔊 System Audio        [▾ Dropdown list ............]  [⟳] │
│     Level: ██████░░░░░░░░░░░░░░░                         │
│                                                          │
│            ┌──────┐  ┌───────┐  ┌──────┐                 │
│            │ ● REC│  │❚❚ PAUSE│  │ ■ STOP│                │
│            └──────┘  └───────┘  └──────┘                 │
│                                                          │
│                      00:42:17                            │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  Status: Recording → C:\Users\...\Meeting_2026-...wav    │
│                                               [⚙ Settings]│
└──────────────────────────────────────────────────────────┘
```

### Widget Details

| Widget               | Type                       | Behaviour |
|----------------------|----------------------------|-----------|
| Mic dropdown         | `ttk.Combobox`             | Populated on start & on Refresh. Disabled while recording. |
| System Audio dropdown| `ttk.Combobox`             | Same as above. Lists output/playback devices for loopback. |
| Refresh button (⟳)  | `ttk.Button`               | Re-enumerates devices. Disabled while recording. |
| REC button           | `ttk.Button`               | Starts recording. Becomes disabled; Pause & Stop become enabled. Background turns red while recording. |
| Pause button         | `ttk.Button`               | Toggles pause. Text changes to "Resume" when paused. |
| Stop button          | `ttk.Button`               | Stops recording and saves file. REC re-enabled. |
| Timer label          | `ttk.Label`                | `HH:MM:SS`, updated every second. Freezes on pause. |
| Mic level bar        | `ttk.Progressbar`          | 0–100 %, updated ~20 times/sec from RMS of mic buffer. |
| System level bar     | `ttk.Progressbar`          | Same, from loopback buffer. |
| Status label         | `ttk.Label` (bottom frame) | Shows idle/recording/saved-file-path messages. |
| Settings button      | `ttk.Button`               | Opens a `tk.Toplevel` with settings from §4.4. |

---

## 7. Architecture

```
┌─────────────┐            ┌──────────────────┐
│   GUI Layer │◄──queue───►│  RecordingEngine  │
│  (tkinter)  │  + after() │                  │
└─────────────┘            │  ┌────────────┐  │
                           │  │ MicCapture │  │──► WAV Writer ──► MP3 Encoder
                           │  │ (WASAPI)   │  │    (stream to disk)
                           │  └────────────┘  │
                           │  ┌────────────┐  │
                           │  │ Loopback   │  │──►
                           │  │ (WASAPI)   │  │
                           │  └────────────┘  │
                           └──────────────────┘
```

### 7.1 Module Breakdown

| Module                | File                    | Responsibility |
|-----------------------|-------------------------|----------------|
| Entry point           | `main.py`               | Parse args, enforce single instance, launch tkinter main loop. |
| Main window           | `ui/main_window.py`     | All widgets, layout, event binding. Uses `root.after()` for periodic UI updates. |
| Settings dialog       | `ui/settings_dialog.py` | Settings form as `tk.Toplevel`, load/save JSON config. |
| Recording engine      | `audio/engine.py`       | Orchestrates mic + loopback capture threads, mixing, writing, MP3 conversion. |
| Mic capture           | `audio/mic_capture.py`  | Opens WASAPI input stream, feeds PCM frames via callback. |
| Loopback capture      | `audio/loopback.py`     | Opens WASAPI loopback stream on selected output device. |
| WAV writer            | `audio/wav_writer.py`   | Receives mic + loopback frames, mixes them to mono, writes to disk incrementally. |
| MP3 encoder           | `audio/mp3_encoder.py`  | Converts finished WAV to MP3 using `lameenc`, deletes the WAV. |
| Device enumerator     | `audio/devices.py`      | Wraps PyAudioWPatch device enumeration, returns structured list. |
| Hotkey listener       | `utils/win32_hotkey_poll.py` | Polls Ctrl+Shift+R via `GetAsyncKeyState` from the tk main thread (avoids GIL issues with PyAudio + `RegisterHotKey`/WndProc). |
| Config manager        | `utils/config.py`       | Read/write `settings.json` from app directory (next to exe). |
| Constants             | `utils/constants.py`    | App name, version, default paths, sample rate, buffer size. |

### 7.2 Threading Model

- **Main thread**: tkinter main loop (`root.mainloop()`). Never blocks.
- **Mic capture thread**: `threading.Thread` running a PyAudioWPatch blocking stream read loop. Pushes frames to a `queue.Queue`.
- **Loopback capture thread**: Same pattern as mic, separate `threading.Thread`.
- **Writer thread**: `threading.Thread` consuming a `queue.Queue` of frame pairs. Averages mic + loopback samples into mono and writes to WAV file. Decouples disk I/O from capture.
- **Level meter updates**: Capture threads compute RMS per chunk and write the value to a `threading`-safe variable. The GUI reads it via `root.after(50, update_meters)` polling loop (no direct cross-thread widget access).
- **MP3 conversion**: Runs synchronously in the writer thread after WAV is closed (takes ~1-3 seconds for a 1-hour file). GUI shows "Converting to MP3..." status during this phase.

### 7.3 Sample Rate Handling

Both the mic and loopback streams may run at different native sample rates (e.g. mic at 44100 Hz, speakers at 48000 Hz). The engine determines the higher rate and resamples the lower stream using linear interpolation (acceptable for voice). Both streams must have identical sample rates before being mixed into the mono WAV file.

---

## 8. Error Handling

| Scenario                              | Behaviour |
|---------------------------------------|-----------|
| No input devices found                | Show warning dialog. Disable REC button. |
| No output devices found               | Show warning dialog. Disable REC button. |
| Device disconnected mid-recording     | Stop recording, save partial file, show notification: "Device disconnected. Partial recording saved." |
| Disk full during recording            | Stop recording, save what was written, show error with free-space info. |
| Microphone access denied (OS privacy) | Show dialog with instructions to enable microphone in Windows Settings. |
| Unsupported sample rate               | Fall back to 44100 Hz. If device rejects it, show error with device name and supported rates. |

---

## 9. Dependencies & Installation

### 9.1 Python Packages (`requirements.txt`)

```
PyAudioWPatch>=0.2.12.6
lameenc>=1.7.0
pystray>=0.19.5
Pillow>=10.0.0
```

`tkinter` and `wave` are part of the Python standard library — no pip install needed.

### 9.2 External

No external tools required. MP3 encoding is handled by `lameenc` (bundled LAME encoder).

### 9.3 Build & Distribution

```bash
pip install pyinstaller
pyinstaller --onedir --windowed --name MeetingRecorder --icon=assets/icon.ico main.py
```

Output: `dist/MeetingRecorder/` folder with `MeetingRecorder.exe` and all dependencies.

---

## 10. Project Folder Structure

```
MeetingsProcessor/
├── main.py
├── requirements.txt
├── settings.json              # created at runtime next to exe
├── assets/
│   └── icon.ico
├── audio/
│   ├── __init__.py
│   ├── engine.py
│   ├── mic_capture.py
│   ├── loopback.py
│   ├── wav_writer.py
│   ├── mp3_encoder.py
│   └── devices.py
├── ui/
│   ├── __init__.py
│   ├── main_window.py
│   └── settings_dialog.py
├── utils/
│   ├── __init__.py
│   ├── win32_hotkey_poll.py
│   ├── config.py
│   └── constants.py
└── SPEC.md
```

---

## 11. Acceptance Criteria

A developer can consider the implementation complete when:

1. User can select any microphone and any speaker/output device from dropdowns.
2. Clicking REC captures the user's mic audio AND the system audio playing through the selected output device simultaneously.
3. The resulting MP3 file (mono, 128 kbps) contains both mic and system audio mixed together, sounding like a normal meeting recording.
4. VU meters show real-time levels for both streams during recording.
5. Pause/Resume works without creating a new file.
6. Ctrl+Shift+R starts/stops recording from any window.
7. The app minimises to system tray and tray icon reflects recording state.
8. Settings persist between sessions.
9. Recordings of 2+ hours complete without crashes or memory growth.
10. App works on a clean Windows 10 machine with no admin rights.
11. No external tools (ffmpeg, etc.) are required — MP3 encoding is built in.

---

## 12. Out of Scope (for now)

- Video recording.
- Transcription / speech-to-text.
- Cloud upload or sharing.
- Per-participant speaker separation (diarization).
- Noise suppression or audio enhancement.
- Scheduled / automatic recording.
- Linux or macOS support.

---

## 13. Open Questions (to confirm before starting)

None — all decisions have been made in this spec. Proceed to implementation.
