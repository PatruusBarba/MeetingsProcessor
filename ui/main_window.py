"""Main tkinter window, tray, and recording control."""

from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw

from audio.devices import AudioDevice, enumerate_devices, open_shared_pyaudio
from audio.engine import RecordingEngine
from ui.settings_dialog import SettingsDialog
from utils.llm_analyzer import LlmAnalyzerThread
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
        root.minsize(900, 480)

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
        self._ignore_transcript_phase_updates = False
        self._listening_phase_text = "Listening…"
        self._decode_tick_after: str | None = None
        self._decode_start_m: float | None = None
        self._decode_est_sec: float = 5.0
        self._decode_ui_gen: int = 0
        self._decode_finish_after: str | None = None

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

        # ── PanedWindow: transcript (left) + key points (right) ──
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED)
        pane.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 4))

        trans_lf = ttk.LabelFrame(pane, text="Live transcript (Parakeet ONNX, offline)", padding=8)
        trans_lf.columnconfigure(0, weight=1)
        trans_lf.rowconfigure(1, minsize=28)  # progress bar (22px) + pady (6px) — fixed row height
        trans_lf.rowconfigure(2, weight=1)
        self._transcript_phase = tk.StringVar(value="Transcription: idle.")
        ttk.Label(trans_lf, textvariable=self._transcript_phase, wraplength=400, justify=tk.LEFT).grid(
            row=0, column=0, sticky="ew", pady=(0, 4)
        )
        self._transcript_load = ttk.Progressbar(trans_lf, mode="indeterminate", length=400)
        self._transcript_load.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        # Start hidden but keep space reserved (no grid_remove — avoids layout jump).
        self._transcript_load.config(style="Hidden.Horizontal.TProgressbar")
        style = ttk.Style()
        style.layout("Hidden.Horizontal.TProgressbar", [])  # empty layout = invisible but keeps space
        self._transcript = scrolledtext.ScrolledText(
            trans_lf,
            height=10,
            wrap=tk.WORD,
            font=("Segoe UI", 10) if sys.platform == "win32" else ("TkDefaultFont", 10),
        )
        self._transcript.grid(row=2, column=0, sticky="nsew")
        # Make read-only via key binding instead of state=DISABLED
        # (DISABLED state breaks see()/yview scroll operations).
        self._transcript.bind("<Key>", lambda e: "break")
        self._transcript.bind("<<Paste>>", lambda e: "break")
        self._transcript.bind("<<Cut>>", lambda e: "break")
        # Segment age highlighting: green (<5s), yellow (5-10s), white (>10s)
        self._transcript.tag_configure("seg_new", background="#c8f7c5")
        self._transcript.tag_configure("seg_recent", background="#fef9c3")
        self._segments: list[tuple[str, float]] = []  # (tag_name, monotonic_time)
        self._seg_counter = 0
        self._seg_tick_id: str | None = None
        pane.add(trans_lf, minsize=300, stretch="always")

        # ── Key Points panel (right side) ──
        kp_lf = ttk.LabelFrame(pane, text="Key Points (LLM analysis)", padding=8)
        kp_lf.columnconfigure(0, weight=1)
        kp_lf.rowconfigure(1, weight=1)
        self._kp_status_var = tk.StringVar(value="LLM: disabled")
        ttk.Label(kp_lf, textvariable=self._kp_status_var, wraplength=300, justify=tk.LEFT).grid(
            row=0, column=0, sticky="ew", pady=(0, 4)
        )
        self._key_points_text = scrolledtext.ScrolledText(
            kp_lf,
            height=10,
            wrap=tk.WORD,
            font=("Segoe UI", 10) if sys.platform == "win32" else ("TkDefaultFont", 10),
        )
        self._key_points_text.grid(row=1, column=0, sticky="nsew")
        self._key_points_text.bind("<Key>", lambda e: "break")
        self._key_points_text.bind("<<Paste>>", lambda e: "break")
        self._key_points_text.bind("<<Cut>>", lambda e: "break")
        self._key_points_text.tag_configure("kp_new", background="#c8f7c5")
        self._key_points_text.tag_configure("kp_recent", background="#fef9c3")
        self._kp_segments: list[tuple[str, float]] = []  # (tag_name, monotonic_time)
        self._kp_seg_counter = 0
        self._kp_prev_lines_set: set[str] = set()
        self._kp_line_tags: dict[str, str] = {}  # stripped_line → tag
        self._kp_tick_id: str | None = None
        pane.add(kp_lf, minsize=250, stretch="always")

        self._llm_thread: LlmAnalyzerThread | None = None

        bottom = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(1, minsize=26)  # reserve space for convert progress bar

        self._status_var = tk.StringVar(value="Ready.")
        self._status_label = ttk.Label(bottom, textvariable=self._status_var, wraplength=480, justify=tk.LEFT)
        self._status_label.grid(row=0, column=0, sticky="w")
        self._status_label.bind("<Button-1>", self._on_status_click)

        self._convert_progress = ttk.Progressbar(bottom, mode="determinate", length=400, maximum=1000)
        self._convert_progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._convert_progress.config(style="Hidden.Horizontal.TProgressbar")

        ttk.Button(bottom, text="⚙ Settings", command=self._open_settings).grid(row=0, column=1, padx=(8, 0))

    def _show_progress_bar(self) -> None:
        self._transcript_load.config(style="Horizontal.TProgressbar")

    def _hide_progress_bar(self) -> None:
        self._transcript_load.stop()
        self._transcript_load.config(style="Hidden.Horizontal.TProgressbar")

    def _transcript_see_end(self) -> None:
        """Scroll to bottom."""
        self._transcript.see(tk.END)

    def _next_seg_tag(self) -> str:
        self._seg_counter += 1
        return f"seg{self._seg_counter}"

    def _clear_transcript(self) -> None:
        self._transcript.delete("1.0", tk.END)
        self._segments.clear()

    def _set_transcript_text(self, text: str) -> None:
        self._transcript.delete("1.0", tk.END)
        self._segments.clear()
        tag = self._next_seg_tag()
        self._transcript.insert(tk.END, text, tag)
        self._transcript.tag_configure(tag)
        self._segments.append((tag, time.monotonic()))
        self._transcript_see_end()
        self._start_seg_aging()

    def _append_transcript_fragment(self, fragment: str) -> None:
        """Single-fragment append (used outside poll batching)."""
        tag = self._next_seg_tag()
        self._transcript.insert(tk.END, fragment, tag)
        self._transcript.tag_configure(tag)
        self._segments.append((tag, time.monotonic()))
        self._transcript_see_end()
        self._start_seg_aging()

    def _batch_append_transcript(self, fragments: list[str]) -> None:
        """Append multiple fragments in one widget transaction — single insert + see()."""
        if not fragments:
            return
        now = time.monotonic()
        tag = self._next_seg_tag()
        self._transcript.insert(tk.END, "".join(fragments), tag)
        self._transcript.tag_configure(tag)
        self._segments.append((tag, now))
        self._transcript_see_end()
        self._start_seg_aging()

    def _start_seg_aging(self) -> None:
        """Ensure the segment color aging tick is running."""
        if self._seg_tick_id is None:
            self._tick_seg_aging()

    def _tick_seg_aging(self) -> None:
        """Update segment colors based on age, prune old segments."""
        self._seg_tick_id = None
        now = time.monotonic()
        still_alive = []
        for tag, t in self._segments:
            age = now - t
            if age < 5.0:
                self._transcript.tag_configure(tag, background="#c8f7c5")
                still_alive.append((tag, t))
            elif age < 10.0:
                self._transcript.tag_configure(tag, background="#fef9c3")
                still_alive.append((tag, t))
            else:
                self._transcript.tag_configure(tag, background="")
        self._segments = still_alive
        if self._segments:
            self._seg_tick_id = self.root.after(500, self._tick_seg_aging)

    @staticmethod
    def _transcript_phase_wants_indeterminate_spinner(msg: str) -> bool:
        low = msg.lower()
        if "listening" in low and "utterances" in low:
            return False
        if "finished" in low or low.strip().endswith("idle."):
            return False
        return any(
            x in low
            for x in (
                "loading",
                "reading",
                "checking",
                "onnx",
                "vocabulary",
                "providers",
                "final utterance",
                "finishing transcript",
            )
        )

    def _cancel_decode_progress_tick(self) -> None:
        if self._decode_tick_after is not None:
            try:
                self.root.after_cancel(self._decode_tick_after)
            except (tk.TclError, ValueError):
                pass
            self._decode_tick_after = None
        self._decode_start_m = None

    def _tick_decode_progress(self) -> None:
        self._decode_tick_after = None
        if self._decode_start_m is None:
            return
        import time

        elapsed = time.monotonic() - self._decode_start_m
        est = max(self._decode_est_sec, 0.8)
        if elapsed < est:
            v = int(900 * min(1.0, elapsed / est))
        else:
            over = min(1.0, (elapsed - est) / max(est * 0.75, 2.0))
            v = min(980, 900 + int(80 * over))
        try:
            self._transcript_load.config(mode="determinate", value=v)
        except tk.TclError:
            return
        self._decode_tick_after = self.root.after(100, self._tick_decode_progress)

    def _begin_decode_progress_ui(self, audio_sec: float) -> None:
        self._decode_ui_gen += 1
        if self._decode_finish_after is not None:
            try:
                self.root.after_cancel(self._decode_finish_after)
            except (tk.TclError, ValueError):
                pass
            self._decode_finish_after = None
        self._cancel_decode_progress_tick()
        import time

        sec = max(0.1, float(audio_sec))
        # Rough wall-time hint for CPU ONNX (adjust if needed); caps keep UI responsive.
        self._decode_est_sec = min(120.0, max(2.5, sec * 0.38))
        self._decode_start_m = time.monotonic()
        self._transcript_phase.set(f"Recognizing speech (~{sec:.1f} s audio)…")
        self._transcript_load.stop()
        self._show_progress_bar()
        self._transcript_load.config(mode="determinate", maximum=1000, value=0)
        self._tick_decode_progress()

    def _end_decode_progress_ui(self, *, restore_listening_phase: bool = True) -> None:
        self._cancel_decode_progress_tick()
        try:
            self._transcript_load.config(mode="determinate", value=1000)
        except tk.TclError:
            pass

        gen = self._decode_ui_gen

        def finish() -> None:
            self._decode_finish_after = None
            if gen != self._decode_ui_gen:
                return
            self._hide_progress_bar()
            if self._ignore_transcript_phase_updates:
                self._transcript_phase.set("Recording stopped — finishing transcript…")
            elif restore_listening_phase:
                self._transcript_phase.set(self._listening_phase_text)

        self._decode_finish_after = self.root.after(180, finish)

    def _set_transcript_phase_ui(self, msg: str, loading: bool) -> None:
        self._transcript_phase.set(msg)
        low = msg.lower()
        if "listening" in low:
            self._listening_phase_text = msg
        if loading:
            self._transcript_load.stop()
            self._show_progress_bar()
            self._transcript_load.config(mode="indeterminate")
            self._transcript_load.start(12)
        else:
            self._cancel_decode_progress_tick()
            self._hide_progress_bar()

    def _poll_transcription(self) -> None:
        # Drain in small batches so Tk stays responsive during heavy transcript traffic.
        processed = 0
        try:
            max_per_tick = 64
            pending_fragments: list[str] = []
            last_full_text: str | None = None
            while processed < max_per_tick:
                try:
                    item = self._transcription_q.get_nowait()
                except queue.Empty:
                    break
                processed += 1
                if item is None:
                    self._ignore_transcript_phase_updates = False
                    self._set_transcript_phase_ui("Transcription: idle.", loading=False)
                    continue
                if isinstance(item, tuple) and len(item) == 2:
                    kind, payload = item
                    if kind == "phase":
                        if self._ignore_transcript_phase_updates:
                            continue
                        low = payload.lower()
                        if "finished" in low:
                            loading = False
                        else:
                            loading = self._transcript_phase_wants_indeterminate_spinner(payload)
                        self._set_transcript_phase_ui(payload, loading=loading)
                    elif kind == "decode_start":
                        info = payload if isinstance(payload, dict) else {}
                        self._begin_decode_progress_ui(float(info.get("sec", 0.0)))
                    elif kind == "decode_end":
                        self._end_decode_progress_ui(
                            restore_listening_phase=not self._ignore_transcript_phase_updates
                        )
                    elif kind == "append":
                        pending_fragments.append(payload)
                    elif kind == "text":
                        pending_fragments.clear()
                        last_full_text = payload
                elif isinstance(item, str):
                    pending_fragments.clear()
                    last_full_text = item
            # Apply text updates once (not per-item)
            if last_full_text is not None:
                self._set_transcript_text(last_full_text)
            if pending_fragments:
                self._batch_append_transcript(pending_fragments)
            if last_full_text is not None or pending_fragments:
                self._feed_llm_transcript()
        except Exception:
            pass  # never break the after() chain
        delay_ms = max(10, 50 - processed) if processed else 120
        self.root.after(delay_ms, self._poll_transcription)

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
        self._teardown_hotkey()
        self._stop_llm_analyzer()
        if self._tray_icon:
            self._tray_icon.stop()

        def _shutdown() -> None:
            if self._engine.is_recording():
                self._engine.stop()
            if self._p_audio:
                self._p_audio.terminate()
            self.root.after(0, self.root.destroy)

        if self._engine.is_recording():
            threading.Thread(target=_shutdown, daemon=True).start()
        else:
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

        def on_convert_progress(fraction: float) -> None:
            self.root.after(0, lambda f=fraction: self._on_convert_progress_ui(f))

        trans_on= bool(self._config.get("transcription_enabled", False))
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
            def _apply(m: str) -> None:
                spin = self._transcript_phase_wants_indeterminate_spinner(m)
                self._set_transcript_phase_ui(m, loading=spin)

            self.root.after(0, lambda m=msg: _apply(m))

        ok, err = self._engine.start(
            mi,
            oi,
            wav_path,
            mp3_path,
            on_disk_error,
            on_convert_start,
            on_convert_done,
            on_convert_error,
            on_convert_progress,
            transcription_enabled=trans_on,
            transcription_text_queue=self._transcription_q if trans_on else None,
            transcription_model_dir=str(self._config.get("transcription_model_dir") or ""),
            transcription_device=str(self._config.get("transcription_device") or "cpu"),
            transcription_min_utterance_sec=float(self._config.get("transcription_min_utterance_sec") or 10.0),
            transcription_max_utterance_sec=float(self._config.get("transcription_max_utterance_sec") or 60.0),
            transcription_end_silence_sec=float(self._config.get("transcription_end_silence_sec") or 0.8),
            transcription_vad_aggressiveness=int(self._config.get("transcription_vad_aggressiveness") or 2),
            transcription_vad_preroll_sec=float(self._config.get("transcription_vad_preroll_sec", 0.55) or 0.55),
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
        self._start_llm_analyzer()

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
        if self._config.get("transcription_enabled", False):
            self._ignore_transcript_phase_updates = True
            self._set_transcript_phase_ui("Recording stopped — finishing transcript…", loading=False)

        def work() -> None:
            try:
                self._engine.stop()
            finally:
                self.root.after(0, self._after_engine_stopped)

        threading.Thread(target=work, daemon=True).start()

    def _after_engine_stopped(self) -> None:
        self._stop_in_progress = False
        self._stop_llm_analyzer()
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
        self._convert_progress.config(style="Horizontal.TProgressbar", value=0)

    def _on_convert_progress_ui(self, fraction: float) -> None:
        pct = int(fraction * 100)
        self._convert_progress.config(value=int(fraction * 1000))
        self._status_var.set(f"Converting to MP3… {pct}%")

    def _on_convert_done_ui(self, path: str) -> None:
        self._converting = False
        self._convert_progress.config(value=1000)
        self.root.after(300, lambda: self._convert_progress.config(
            style="Hidden.Horizontal.TProgressbar"))
        self._last_saved_mp3 = path
        self._status_var.set(f"Saved: {path}")
        self._after_stop_cleanup()

    def _on_convert_error_ui(self, err: str) -> None:
        self._converting = False
        self._convert_progress.config(style="Hidden.Horizontal.TProgressbar")
        messagebox.showerror(APP_NAME, f"MP3 conversion failed:\n{err}")
        self._status_var.set("Conversion failed. Check for leftover WAV in output folder.")
        self._after_stop_cleanup()

    def _after_stop_cleanup(self) -> None:
        self._rec_btn.config(state=tk.NORMAL)
        self._pause_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.DISABLED)
        self._mic_combo.config(state="readonly")
        self._out_combo.config(state="readonly")

    # ── LLM analysis ──

    def _start_llm_analyzer(self) -> None:
        """Start LLM analyzer thread if enabled in config."""
        self._stop_llm_analyzer()
        if not self._config.get("llm_analysis_enabled", False):
            self._kp_status_var.set("LLM: disabled")
            return
        base_url = self._config.get("llm_base_url", "http://localhost:1234/v1")
        model = self._config.get("llm_model", "")
        interval = float(self._config.get("llm_analysis_interval_sec", 20.0))

        def on_result(text: str) -> None:
            self.root.after(0, lambda t=text: self._on_llm_result(t))

        def on_error(msg: str) -> None:
            self.root.after(0, lambda m=msg: self._kp_status_var.set(m))

        def on_status(msg: str) -> None:
            self.root.after(0, lambda m=msg: self._kp_status_var.set(m))

        self._llm_thread = LlmAnalyzerThread(
            base_url, model, interval, on_result, on_error, on_status,
        )
        self._llm_thread.start()

    def _stop_llm_analyzer(self) -> None:
        if self._llm_thread is not None:
            self._llm_thread.stop()
            self._llm_thread = None

    def _feed_llm_transcript(self) -> None:
        """Send current transcript text to LLM analyzer (if running)."""
        if self._llm_thread is None:
            return
        text = self._transcript.get("1.0", tk.END).strip()
        if text:
            self._llm_thread.update_transcript(text)

    def _on_llm_result(self, text: str) -> None:
        new_lines = [l for l in text.splitlines() if l.strip()]
        now = time.monotonic()

        # Build lookup: stripped_line → (tag, timestamp) for still-aging lines
        old_tag_map: dict[str, tuple[str, float]] = {}
        for tag, t in self._kp_segments:
            # Find which previous line this tag belonged to
            for prev_line, prev_tag in self._kp_line_tags.items():
                if prev_tag == tag:
                    old_tag_map[prev_line] = (tag, t)
                    break

        self._key_points_text.delete("1.0", tk.END)
        new_segments: list[tuple[str, float]] = []
        new_line_tags: dict[str, str] = {}

        for i, line in enumerate(new_lines):
            if i > 0:
                self._key_points_text.insert(tk.END, "\n")
            stripped = line.strip()
            if stripped in old_tag_map:
                # Reuse existing tag and timestamp (preserve aging)
                tag, t = old_tag_map[stripped]
                self._key_points_text.insert(tk.END, line, tag)
                new_segments.append((tag, t))
                new_line_tags[stripped] = tag
            elif stripped in self._kp_prev_lines_set:
                # Old line, aging already finished — no tag needed
                self._key_points_text.insert(tk.END, line)
            else:
                # New/changed line — assign fresh tag
                self._kp_seg_counter += 1
                tag = f"kp{self._kp_seg_counter}"
                self._key_points_text.insert(tk.END, line, tag)
                new_segments.append((tag, now))
                new_line_tags[stripped] = tag

        self._kp_segments = new_segments
        self._kp_line_tags = new_line_tags
        self._kp_prev_lines_set = {l.strip() for l in new_lines}
        self._start_kp_aging()

    def _start_kp_aging(self) -> None:
        if self._kp_tick_id is None:
            self._tick_kp_aging()

    def _tick_kp_aging(self) -> None:
        self._kp_tick_id = None
        now = time.monotonic()
        still_alive = []
        for tag, t in self._kp_segments:
            age = now - t
            if age < 20.0:
                self._key_points_text.tag_configure(tag, background="#c8f7c5")
                still_alive.append((tag, t))
            elif age < 40.0:
                self._key_points_text.tag_configure(tag, background="#fef9c3")
                still_alive.append((tag, t))
            else:
                self._key_points_text.tag_configure(tag, background="")
        self._kp_segments = still_alive
        if self._kp_segments:
            self._kp_tick_id = self.root.after(500, self._tick_kp_aging)

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
