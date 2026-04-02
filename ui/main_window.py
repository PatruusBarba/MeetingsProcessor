"""Main tkinter window, tray, and recording control."""

from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw

from audio.devices import AudioDevice, enumerate_devices, open_shared_pyaudio
from audio.engine import RecordingEngine
from ui.settings_dialog import SettingsDialog
from utils.config import load_config, save_config
from utils.constants import APP_NAME, app_dir

if sys.platform == "win32":
    from utils.win32_hotkey_poll import poll_ctrl_shift_r_edge

if TYPE_CHECKING:
    import pyaudiowpatch as pyaudio


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_NAME)
        root.minsize(520, 380)

        self._config = load_config()
        self._p_audio: pyaudio.PyAudio | None = None
        try:
            self._p_audio = open_shared_pyaudio()
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Audio engine failed to start:\n{e}")
            root.after(100, root.destroy)
            return

        self._engine = RecordingEngine(self._p_audio)
        self._inputs: list[AudioDevice] = []
        self._outputs: list[AudioDevice] = []

        self._recording_started_monotonic: float | None = None
        self._paused_accum_sec: float = 0.0
        self._pause_started_monotonic: float | None = None

        self._last_saved_mp3: str | None = None
        self._converting = False
        self._stop_in_progress = False
        self._transcription_q: queue.Queue = queue.Queue()

        self._tray_icon: pystray.Icon | None = None
        self._tray_thread: threading.Thread | None = None
        self._tray_state = "idle"

        self._hotkey_combo_down = False
        self._hotkey_after_id: str | None = None

        self._build_ui()
        self._refresh_devices(select_saved=True)

        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._poll_levels()
        self._poll_engine_errors()

        if self._config.get("global_hotkey_enabled", True):
            self._start_hotkey_polling()

        if self._config.get("start_minimized", False):
            root.after(200, self._minimize_to_tray)

        self._start_tray()
        self._update_timer()
        self._poll_transcription()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)

        ttk.Label(main, text="🎤 Microphone").grid(row=0, column=0, sticky="w")
        self._mic_combo = ttk.Combobox(main, state="readonly", width=55)
        self._mic_combo.grid(row=0, column=1, sticky="ew", padx=(8, 4))
        ttk.Button(main, text="⟳", width=3, command=lambda: self._refresh_devices(select_saved=False)).grid(
            row=0, column=2
        )
        self._mic_level = ttk.Progressbar(main, length=300, mode="determinate", maximum=100)
        self._mic_level.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(4, 12))

        ttk.Label(main, text="🔊 System Audio").grid(row=2, column=0, sticky="w")
        self._out_combo = ttk.Combobox(main, state="readonly", width=55)
        self._out_combo.grid(row=2, column=1, sticky="ew", padx=(8, 4))
        ttk.Button(main, text="⟳", width=3, command=lambda: self._refresh_devices(select_saved=False)).grid(
            row=2, column=2
        )
        self._sys_level = ttk.Progressbar(main, length=300, mode="determinate", maximum=100)
        self._sys_level.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(4, 16))

        btn_row = ttk.Frame(main)
        btn_row.grid(row=4, column=0, columnspan=3, pady=8)
        self._rec_btn = tk.Button(
            btn_row,
            text="● REC",
            command=self._toggle_recording_hotkey,
            padx=12,
            pady=4,
        )
        self._rec_btn.pack(side=tk.LEFT, padx=6)
        self._pause_btn = ttk.Button(btn_row, text="❚❚ PAUSE", command=self._toggle_pause, state=tk.DISABLED)
        self._pause_btn.pack(side=tk.LEFT, padx=6)
        self._stop_btn = ttk.Button(btn_row, text="■ STOP", command=self._stop_recording, state=tk.DISABLED)
        self._stop_btn.pack(side=tk.LEFT, padx=6)

        self._timer_var = tk.StringVar(value="00:00:00")
        ttk.Label(main, textvariable=self._timer_var, font=("TkDefaultFont", 16)).grid(
            row=5, column=0, columnspan=3, pady=12
        )

        trans_lf = ttk.LabelFrame(self.root, text="Live transcript (Parakeet ONNX, offline)", padding=8)
        trans_lf.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 4))
        trans_lf.columnconfigure(0, weight=1)
        trans_lf.rowconfigure(2, weight=1)
        self._transcript_phase = tk.StringVar(value="Transcription: idle.")
        ttk.Label(trans_lf, textvariable=self._transcript_phase, wraplength=520, justify=tk.LEFT).grid(
            row=0, column=0, sticky="ew", pady=(0, 4)
        )
        self._transcript_load = ttk.Progressbar(trans_lf, mode="indeterminate", length=400)
        self._transcript_load.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self._transcript_load.grid_remove()
        self._transcript = scrolledtext.ScrolledText(
            trans_lf,
            height=10,
            wrap=tk.WORD,
            font=("Segoe UI", 10) if sys.platform == "win32" else ("TkDefaultFont", 10),
            state=tk.DISABLED,
        )
        self._transcript.grid(row=2, column=0, sticky="nsew")

        bottom = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        self._status_var = tk.StringVar(value="Ready.")
        self._status_label = ttk.Label(bottom, textvariable=self._status_var, wraplength=480, justify=tk.LEFT)
        self._status_label.grid(row=0, column=0, sticky="w")
        self._status_label.bind("<Button-1>", self._on_status_click)

        ttk.Button(bottom, text="⚙ Settings", command=self._open_settings).grid(row=0, column=1, padx=(8, 0))

    def _clear_transcript(self) -> None:
        self._transcript.config(state=tk.NORMAL)
        self._transcript.delete("1.0", tk.END)
        self._transcript.config(state=tk.DISABLED)

    def _set_transcript_text(self, text: str) -> None:
        self._transcript.config(state=tk.NORMAL)
        self._transcript.delete("1.0", tk.END)
        self._transcript.insert(tk.END, text)
        self._transcript.see(tk.END)
        self._transcript.config(state=tk.DISABLED)

    def _set_transcript_phase_ui(self, msg: str, loading: bool) -> None:
        self._transcript_phase.set(msg)
        if loading:
            self._transcript_load.grid()
            self._transcript_load.start(12)
        else:
            self._transcript_load.stop()
            self._transcript_load.grid_remove()

    def _poll_transcription(self) -> None:
        while True:
            try:
                item = self._transcription_q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                self._set_transcript_phase_ui("Transcription: idle.", loading=False)
                continue
            if isinstance(item, tuple) and len(item) == 2:
                kind, payload = item
                if kind == "phase":
                    low = payload.lower()
                    if "ready" in low and "capturing" in low:
                        loading = False
                    else:
                        loading = any(
                            x in low
                            for x in (
                                "loading",
                                "reading",
                                "checking",
                                "decoding",
                                "stopping",
                            )
                        )
                    self._set_transcript_phase_ui(payload, loading=loading)
                elif kind == "text":
                    self._set_transcript_text(payload)
            elif isinstance(item, str):
                self._set_transcript_text(item)
        self.root.after(120, self._poll_transcription)

    def _icon_path(self) -> str:
        base = app_dir()
        ico = os.path.join(base, "assets", "icon.ico")
        if os.path.isfile(ico):
            return ico
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.ico")

    def _start_hotkey_polling(self) -> None:
        """Poll Ctrl+Shift+R from the tk main thread only (avoids GIL crash with PyAudio)."""
        if sys.platform != "win32":
            return
        self._stop_hotkey_polling()
        self._hotkey_combo_down = False

        def tick() -> None:
            if not self._config.get("global_hotkey_enabled", True):
                self._hotkey_after_id = None
                return
            fired, self._hotkey_combo_down = poll_ctrl_shift_r_edge(self._hotkey_combo_down)
            if fired and not self._converting:
                self._toggle_recording_hotkey()
            self._hotkey_after_id = self.root.after(100, tick)

        self._hotkey_after_id = self.root.after(100, tick)

    def _stop_hotkey_polling(self) -> None:
        if self._hotkey_after_id is not None:
            try:
                self.root.after_cancel(self._hotkey_after_id)
            except tk.TclError:
                pass
            self._hotkey_after_id = None
        self._hotkey_combo_down = False

    def _teardown_hotkey(self) -> None:
        self._stop_hotkey_polling()

    def _tray_image(self, state: str) -> Image.Image:
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        if state == "recording":
            fill = (220, 50, 50, 255)
        elif state == "paused":
            fill = (230, 200, 50, 255)
        else:
            fill = (140, 140, 140, 255)
        draw.ellipse((8, 8, size - 8, size - 8), fill=fill)
        return img

    def _start_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Show Window", self._tray_show),
            pystray.MenuItem("Start Recording", self._tray_start_rec),
            pystray.MenuItem("Stop Recording", self._tray_stop_rec),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._tray_quit),
        )
        self._tray_icon = pystray.Icon(
            "meeting_recorder",
            self._tray_image("idle"),
            APP_NAME,
            menu,
        )

        def run_tray() -> None:
            assert self._tray_icon is not None
            self._tray_icon.run()

        self._tray_thread = threading.Thread(target=run_tray, daemon=True)
        self._tray_thread.start()

    def _set_tray_state(self, state: str) -> None:
        self._tray_state = state
        if not self._tray_icon:
            return
        img = self._tray_image(state)
        icon = self._tray_icon

        def upd() -> None:
            icon.icon = img

        self.root.after(0, upd)

    def _tray_show(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._show_from_tray)

    def _show_from_tray(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _tray_start_rec(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._start_recording)

    def _tray_stop_rec(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._stop_recording)

    def _tray_quit(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._quit_app)

    def _minimize_to_tray(self) -> None:
        self.root.withdraw()

    def _on_close(self) -> None:
        if self._config.get("minimize_to_tray_on_close", True) and self._tray_icon:
            self._minimize_to_tray()
        else:
            self._quit_app()

    def _quit_app(self) -> None:
        if self._engine.is_recording():
            self._engine.stop()
        self._teardown_hotkey()
        if self._tray_icon:
            self._tray_icon.stop()
        if self._p_audio:
            self._p_audio.terminate()
        self.root.destroy()

    def _open_settings(self) -> None:
        SettingsDialog(self.root, self._config, self._on_settings_saved)

    def _on_settings_saved(self, cfg: dict) -> None:
        self._config = cfg
        if cfg.get("global_hotkey_enabled", True):
            self._start_hotkey_polling()
        else:
            self._teardown_hotkey()

    def _refresh_devices(self, select_saved: bool) -> None:
        assert self._p_audio is not None
        self._inputs, self._outputs = enumerate_devices(self._p_audio)

        mic_labels = [d.label() for d in self._inputs]
        out_labels = [d.label() for d in self._outputs]
        self._mic_combo["values"] = mic_labels
        self._out_combo["values"] = out_labels

        if not self._inputs:
            messagebox.showwarning(APP_NAME, "No WASAPI microphone devices found. Recording is disabled.")
            self._rec_btn.config(state=tk.DISABLED)
        else:
            self._rec_btn.config(state=tk.NORMAL if not self._engine.is_recording() else tk.DISABLED)

        if not self._outputs:
            messagebox.showwarning(APP_NAME, "No WASAPI output devices found. Recording is disabled.")
            self._rec_btn.config(state=tk.DISABLED)

        if select_saved:
            li = self._config.get("last_input_device_id")
            lo = self._config.get("last_output_device_id")
            if li is not None:
                for i, d in enumerate(self._inputs):
                    if d.device_index == li:
                        self._mic_combo.current(i)
                        break
                else:
                    if mic_labels:
                        self._mic_combo.current(0)
            elif mic_labels:
                self._mic_combo.current(0)
            if lo is not None:
                for i, d in enumerate(self._outputs):
                    if d.device_index == lo:
                        self._out_combo.current(i)
                        break
                else:
                    if out_labels:
                        self._out_combo.current(0)
            elif out_labels:
                self._out_combo.current(0)

    def _selected_mic_index(self) -> int | None:
        i = self._mic_combo.current()
        if i < 0 or i >= len(self._inputs):
            return None
        return self._inputs[i].device_index

    def _selected_out_index(self) -> int | None:
        i = self._out_combo.current()
        if i < 0 or i >= len(self._outputs):
            return None
        return self._outputs[i].device_index

    def _save_device_prefs(self) -> None:
        mi = self._selected_mic_index()
        oi = self._selected_out_index()
        if mi is not None:
            self._config["last_input_device_id"] = mi
        if oi is not None:
            self._config["last_output_device_id"] = oi
        save_config(self._config)

    def _elapsed_recording_seconds(self) -> float:
        import time

        if self._recording_started_monotonic is None:
            return 0.0
        now = time.monotonic()
        extra_pause = 0.0
        if self._pause_started_monotonic is not None:
            extra_pause = now - self._pause_started_monotonic
        return now - self._recording_started_monotonic - self._paused_accum_sec - extra_pause

    def _format_hms(self, seconds: float) -> str:
        s = max(0, int(seconds))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    def _update_timer(self) -> None:
        if self._engine.is_recording() and not self._engine.is_paused():
            self._timer_var.set(self._format_hms(self._elapsed_recording_seconds()))
        self.root.after(1000, self._update_timer)

    def _poll_levels(self) -> None:
        if self._engine.is_recording():
            mic, sysv = self._engine.get_levels()
            self._mic_level["value"] = mic
            self._sys_level["value"] = sysv
        else:
            self._mic_level["value"] = 0
            self._sys_level["value"] = 0
        self.root.after(50, self._poll_levels)

    def _poll_engine_errors(self) -> None:
        for kind, msg in self._engine.get_errors():
            if kind.endswith("_open") and "denied" in msg.lower():
                messagebox.showerror(
                    APP_NAME,
                    "Microphone access may be denied.\n"
                    "Enable the microphone in Windows Settings → Privacy → Microphone.",
                )
            else:
                messagebox.showerror(APP_NAME, f"Recording error ({kind}):\n{msg}")
            self.root.after(0, self._stop_recording)
        self.root.after(500, self._poll_engine_errors)

    def _toggle_recording_hotkey(self) -> None:
        if self._converting:
            return
        if self._engine.is_recording():
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self._converting or self._engine.is_recording():
            return
        mi = self._selected_mic_index()
        oi = self._selected_out_index()
        if mi is None or oi is None:
            messagebox.showwarning(APP_NAME, "Select microphone and system output devices.")
            return

        out_dir = self._config.get("output_directory") or os.path.join(app_dir(), "recordings")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Cannot create output folder:\n{e}")
            return

        start_ts = dt.datetime.now()
        base = start_ts.strftime("Meeting_%Y-%m-%d_%H-%M-%S")
        wav_path = os.path.join(out_dir, base + ".wav")
        mp3_path = os.path.join(out_dir, base + ".mp3")

        self._save_device_prefs()

        def on_disk_error(err: str) -> None:
            self.root.after(0, lambda: self._on_disk_error_ui(err))

        def on_convert_start() -> None:
            self.root.after(0, self._on_convert_start_ui)

        def on_convert_done(path: str) -> None:
            self.root.after(0, lambda p=path: self._on_convert_done_ui(p))

        def on_convert_error(err: str) -> None:
            self.root.after(0, lambda: self._on_convert_error_ui(err))

        trans_on = bool(self._config.get("transcription_enabled", False))
        if trans_on:
            while True:
                try:
                    self._transcription_q.get_nowait()
                except queue.Empty:
                    break
            self._clear_transcript()

        def on_model_loading() -> None:
            self.root.after(
                0,
                lambda: self._set_transcript_phase_ui(
                    "Transcription: loading ONNX into RAM (see status below; can take 1–2 min)…",
                    loading=True,
                ),
            )

        def on_transcription_error(msg: str) -> None:
            def _err(m: str) -> None:
                self._set_transcript_phase_ui(f"Transcription error: {m[:200]}", loading=False)
                messagebox.showerror(APP_NAME, m)

            self.root.after(0, lambda m=msg: _err(m))

        def on_transcription_status(msg: str) -> None:
            self.root.after(0, lambda m=msg: self._set_transcript_phase_ui(m, loading=True))

        ok, err = self._engine.start(
            mi,
            oi,
            wav_path,
            mp3_path,
            on_disk_error,
            on_convert_start,
            on_convert_done,
            on_convert_error,
            transcription_enabled=trans_on,
            transcription_text_queue=self._transcription_q if trans_on else None,
            transcription_model_dir=str(self._config.get("transcription_model_dir") or ""),
            transcription_device=str(self._config.get("transcription_device") or "cpu"),
            transcription_refresh_sec=float(self._config.get("transcription_refresh_sec") or 0.35),
            on_transcription_model_loading=on_model_loading if trans_on else None,
            on_transcription_error=on_transcription_error if trans_on else None,
            on_transcription_status=on_transcription_status if trans_on else None,
        )
        if not ok:
            messagebox.showerror(APP_NAME, err or "Failed to start recording.")
            return

        import time

        self._recording_started_monotonic = time.monotonic()
        self._paused_accum_sec = 0.0
        self._pause_started_monotonic = None
        self._last_saved_mp3 = None

        self._rec_btn.config(state=tk.DISABLED)
        self._pause_btn.config(state=tk.NORMAL, text="❚❚ PAUSE")
        self._stop_btn.config(state=tk.NORMAL)
        self._mic_combo.config(state=tk.DISABLED)
        self._out_combo.config(state=tk.DISABLED)
        self._status_var.set(f"Recording → {wav_path}")
        self._set_tray_state("recording")
        self._style_recording(True)

    def _style_recording(self, active: bool) -> None:
        if active:
            self._rec_btn.configure(bg="#ff6666", activebackground="#ff4444")
        else:
            self._rec_btn.configure(bg="SystemButtonFace", activebackground="SystemButtonFace")

    def _toggle_pause(self) -> None:
        if not self._engine.is_recording():
            return
        import time

        if self._engine.is_paused():
            if self._pause_started_monotonic is not None:
                self._paused_accum_sec += time.monotonic() - self._pause_started_monotonic
                self._pause_started_monotonic = None
            self._engine.resume()
            self._pause_btn.config(text="❚❚ PAUSE")
            self._set_tray_state("recording")
        else:
            self._pause_started_monotonic = time.monotonic()
            self._engine.pause()
            self._pause_btn.config(text="▶ RESUME")
            self._set_tray_state("paused")

    def _stop_recording(self) -> None:
        if not self._engine.is_recording() or self._stop_in_progress:
            return
        self._stop_in_progress = True

        self._stop_btn.config(state=tk.DISABLED)
        self._pause_btn.config(state=tk.DISABLED)
        if not self._converting:
            self._status_var.set("Stopping…")

        def work() -> None:
            try:
                self._engine.stop()
            finally:
                self.root.after(0, self._after_engine_stopped)

        threading.Thread(target=work, daemon=True).start()

    def _after_engine_stopped(self) -> None:
        self._stop_in_progress = False
        self._recording_started_monotonic = None
        self._paused_accum_sec = 0.0
        self._pause_started_monotonic = None

        self._rec_btn.config(state=tk.NORMAL)
        self._pause_btn.config(state=tk.DISABLED, text="❚❚ PAUSE")
        self._stop_btn.config(state=tk.DISABLED)
        self._mic_combo.config(state="readonly")
        self._out_combo.config(state="readonly")
        self._timer_var.set("00:00:00")
        self._set_tray_state("idle")
        self._style_recording(False)
        # Writer schedules convert UI before stop() returns; this callback is queued after
        # those, so do not overwrite "Saved:" / "Converting…" / errors.
        if self._status_var.get() == "Stopping…":
            self._status_var.set("Ready.")

    def _on_disk_error_ui(self, err: str) -> None:
        messagebox.showerror(APP_NAME, f"Disk error while recording:\n{err}")
        self._after_stop_cleanup()

    def _on_convert_start_ui(self) -> None:
        self._converting = True
        self._status_var.set("Converting to MP3…")

    def _on_convert_done_ui(self, path: str) -> None:
        self._converting = False
        self._last_saved_mp3 = path
        self._status_var.set(f"Saved: {path}")
        self._after_stop_cleanup()

    def _on_convert_error_ui(self, err: str) -> None:
        self._converting = False
        messagebox.showerror(APP_NAME, f"MP3 conversion failed:\n{err}")
        self._status_var.set("Conversion failed. Check for leftover WAV in output folder.")
        self._after_stop_cleanup()

    def _after_stop_cleanup(self) -> None:
        self._rec_btn.config(state=tk.NORMAL)
        self._pause_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.DISABLED)
        self._mic_combo.config(state="readonly")
        self._out_combo.config(state="readonly")

    def _on_status_click(self, _ev=None) -> None:
        path = self._last_saved_mp3
        if not path or not os.path.isfile(path):
            return
        folder = os.path.dirname(os.path.abspath(path))
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"', shell=True)

def run_app() -> None:
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()
