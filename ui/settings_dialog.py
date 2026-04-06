"""Settings Toplevel."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from utils.config import save_config
from utils.constants import PARAKEET_ONNX_REPO_ID, bundled_parakeet_onnx_dir
from utils.onnx_model_bundle import (
    delete_bundled_model,
    download_parakeet_bundle,
    is_bundle_complete,
)


class SettingsDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        config: dict,
        on_saved: Callable[[dict], None],
    ) -> None:
        super().__init__(parent)
        self.title("Settings")
        self._config = dict(config)
        self._on_saved = on_saved
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        row = 0
        ttk.Label(frm, text="Output directory:").grid(row=row, column=0, sticky="w")
        row += 1
        self._dir_var = tk.StringVar(value=self._config.get("output_directory") or "")
        ent = ttk.Entry(frm, textvariable=self._dir_var, width=50)
        ent.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(frm, text="Browse…", command=self._browse).grid(row=row, column=2, padx=(8, 0))
        row += 1

        self._tray_var = tk.BooleanVar(value=bool(self._config.get("minimize_to_tray_on_close", True)))
        ttk.Checkbutton(
            frm,
            text="Minimize to tray when closing window",
            variable=self._tray_var,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=4)
        row += 1

        self._start_min_var = tk.BooleanVar(value=bool(self._config.get("start_minimized", False)))
        ttk.Checkbutton(
            frm,
            text="Start minimized to tray",
            variable=self._start_min_var,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=4)
        row += 1

        self._hotkey_var = tk.BooleanVar(value=bool(self._config.get("global_hotkey_enabled", True)))
        ttk.Checkbutton(
            frm,
            text="Enable global hotkey (Ctrl+Shift+R)",
            variable=self._hotkey_var,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=4)
        row += 1

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=3, sticky="ew", pady=12)
        row += 1
        ttk.Label(
            frm,
            text="Live transcription (Parakeet TDT V3 INT8 ONNX)",
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self._trans_on = tk.BooleanVar(value=bool(self._config.get("transcription_enabled", False)))
        ttk.Checkbutton(
            frm,
            text="Enable streaming transcript during recording",
            variable=self._trans_on,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 2))
        row += 1

        bundled = bundled_parakeet_onnx_dir()
        self._model_status = tk.StringVar()
        self._custom_var = tk.BooleanVar(value=bool((self._config.get("transcription_model_dir") or "").strip()))
        self._mdir_var = tk.StringVar(value=str(self._config.get("transcription_model_dir") or ""))

        ttk.Label(frm, text="Model location:", font=("TkDefaultFont", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(6, 2)
        )
        row += 1
        ttk.Label(frm, textvariable=self._model_status, wraplength=500, justify=tk.LEFT).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1

        ttk.Label(frm, text=f"Default folder (next to app):", font=("TkDefaultFont", 8)).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1
        ttk.Label(frm, text=bundled, font=("Consolas", 8), foreground="gray").grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1

        dl_frm = ttk.Frame(frm)
        dl_frm.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 4))
        self._dl_btn = ttk.Button(dl_frm, text="Download model (~670 MB)", command=self._download_model)
        self._dl_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._del_btn = ttk.Button(dl_frm, text="Delete downloaded model", command=self._delete_model)
        self._del_btn.pack(side=tk.LEFT)
        row += 1

        self._dl_progress = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self._dl_progress, font=("TkDefaultFont", 8), foreground="gray").grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1

        ttk.Label(frm, text=f"Source: Hugging Face `{PARAKEET_ONNX_REPO_ID}`", font=("TkDefaultFont", 8), foreground="gray").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        row += 1

        self._custom_chk = ttk.Checkbutton(
            frm,
            text="Use a custom folder instead",
            variable=self._custom_var,
            command=self._toggle_custom,
        )
        self._custom_chk.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self._custom_row = row
        self._mdir_ent = ttk.Entry(frm, textvariable=self._mdir_var, width=48, state=tk.DISABLED)
        self._mdir_ent.grid(row=row, column=0, columnspan=2, sticky="ew", padx=(20, 0))
        self._mdir_btn = ttk.Button(frm, text="Browse…", command=self._browse_model, state=tk.DISABLED)
        self._mdir_btn.grid(row=row, column=2, padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Inference device:").grid(row=row, column=0, sticky="w")
        self._dev_var = tk.StringVar(value=str(self._config.get("transcription_device") or "cpu"))
        ttk.Combobox(
            frm,
            textvariable=self._dev_var,
            values=("cpu", "cuda"),
            width=16,
            state="readonly",
        ).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Pause at end of phrase (sec) → run recognition:").grid(row=row, column=0, sticky="w")
        self._sil_var = tk.StringVar(value=str(self._config.get("transcription_end_silence_sec", 0.8)))
        ttk.Entry(frm, textvariable=self._sil_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Max phrase length (sec), then force split:").grid(row=row, column=0, sticky="w")
        self._max_u_var = tk.StringVar(value=str(self._config.get("transcription_max_utterance_sec", 60.0)))
        ttk.Entry(frm, textvariable=self._max_u_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Skip ONNX if only silence for (sec):").grid(row=row, column=0, sticky="w")
        self._min_u_var = tk.StringVar(value=str(self._config.get("transcription_min_utterance_sec", 10.0)))
        ttk.Entry(frm, textvariable=self._min_u_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="VAD aggressiveness (0–3):").grid(row=row, column=0, sticky="w")
        self._vad_var = tk.StringVar(value=str(self._config.get("transcription_vad_aggressiveness", 2)))
        ttk.Combobox(
            frm,
            textvariable=self._vad_var,
            values=("0", "1", "2", "3"),
            width=8,
            state="readonly",
        ).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="VAD engine:").grid(row=row, column=0, sticky="w")
        _vb = str(self._config.get("transcription_vad_backend") or "auto").strip().lower()
        if _vb not in ("auto", "silero", "webrtc"):
            _vb = "auto"
        self._vad_back_var = tk.StringVar(value=_vb)
        ttk.Combobox(
            frm,
            textvariable=self._vad_back_var,
            values=("auto", "silero", "webrtc"),
            width=10,
            state="readonly",
        ).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Silero threshold (0.05–0.95, lower=sensitive):").grid(row=row, column=0, sticky="w")
        self._silero_thr_var = tk.StringVar(value=str(self._config.get("transcription_silero_threshold", 0.35)))
        ttk.Entry(frm, textvariable=self._silero_thr_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Speech start pre-roll (sec):").grid(row=row, column=0, sticky="w")
        self._preroll_var = tk.StringVar(
            value=str(self._config.get("transcription_vad_preroll_sec", 0.55))
        )
        ttk.Entry(frm, textvariable=self._preroll_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        hint = ttk.Label(
            frm,
            text=(
                "While you talk, the buffer grows. After a pause (first setting), that phrase is sent to the model — "
                "short words work; you do not wait for max length. Max length only cuts an uninterrupted monologue. "
                "Third setting: if the mic picks up no speech for that long, audio is dropped without running ONNX "
                "(CPU saver only). VAD engine: auto uses Silero if package silero-vad-lite is installed (often better "
                "on short words), else webrtcvad. pip install silero-vad-lite — recommended. Silero threshold only "
                "applies when Silero is active. Pre-roll: audio kept before detected speech start."
            ),
            font=("TkDefaultFont", 8),
            foreground="gray",
            wraplength=480,
        )
        hint.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        row += 1

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=row, column=0, columnspan=3, pady=(16, 0))
        ttk.Button(btn_frm, text="Save", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frm, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=4)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        self._toggle_custom()
        self._refresh_model_status()

    def _effective_model_dir(self) -> str:
        if self._custom_var.get():
            return self._mdir_var.get().strip()
        return bundled_parakeet_onnx_dir()

    def _refresh_model_status(self) -> None:
        d = self._effective_model_dir()
        if is_bundle_complete(d):
            self._model_status.set("Status: model files OK — ready to transcribe.")
        elif os.path.isdir(d):
            self._model_status.set("Status: folder exists but files incomplete — click Download.")
        else:
            self._model_status.set("Status: model not installed — click Download.")

    def _toggle_custom(self) -> None:
        if self._custom_var.get():
            self._mdir_ent.config(state=tk.NORMAL)
            self._mdir_btn.config(state=tk.NORMAL)
        else:
            self._mdir_ent.config(state=tk.DISABLED)
            self._mdir_btn.config(state=tk.DISABLED)
        self._refresh_model_status()

    def _download_model(self) -> None:
        dest = bundled_parakeet_onnx_dir()
        self._dl_btn.config(state=tk.DISABLED)
        self._del_btn.config(state=tk.DISABLED)
        self._dl_progress.set("Starting…")

        def on_status(msg: str) -> None:
            self.after(0, lambda m=msg: self._dl_progress.set(m))

        def on_done(ok: bool, msg: str) -> None:
            def fin() -> None:
                self._dl_btn.config(state=tk.NORMAL)
                self._del_btn.config(state=tk.NORMAL)
                self._dl_progress.set(msg if ok else "")
                self._refresh_model_status()
                if ok:
                    messagebox.showinfo("Meeting Audio Recorder", f"Model saved to:\n{msg}")
                else:
                    messagebox.showerror("Meeting Audio Recorder", msg)

            self.after(0, fin)

        download_parakeet_bundle(on_status, on_done, dest_dir=dest)

    def _delete_model(self) -> None:
        if not messagebox.askyesno(
            "Meeting Audio Recorder",
            "Remove the downloaded ONNX model from the app folder?\n\n"
            f"{bundled_parakeet_onnx_dir()}",
        ):
            return
        self._del_btn.config(state=tk.DISABLED)
        self._dl_btn.config(state=tk.DISABLED)

        def on_done(ok: bool, msg: str) -> None:
            def fin() -> None:
                self._del_btn.config(state=tk.NORMAL)
                self._dl_btn.config(state=tk.NORMAL)
                self._refresh_model_status()
                if ok:
                    messagebox.showinfo("Meeting Audio Recorder", msg)
                else:
                    messagebox.showerror("Meeting Audio Recorder", msg)

            self.after(0, fin)

        delete_bundled_model(on_done)

    def _browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self._dir_var.get() or os.path.expanduser("~"))
        if d:
            self._dir_var.set(d)

    def _browse_model(self) -> None:
        d = filedialog.askdirectory(initialdir=self._mdir_var.get() or os.path.expanduser("~"))
        if d:
            self._mdir_var.set(d)
            self._refresh_model_status()

    def _save(self) -> None:
        if self._custom_var.get() and not self._mdir_var.get().strip():
            messagebox.showwarning(
                "Meeting Audio Recorder",
                "Custom model folder is checked but path is empty. Browse to a folder or turn off custom.",
            )
            return
        out = self._dir_var.get().strip()
        if not out:
            out = self._config.get("output_directory") or ""
        self._config["output_directory"] = os.path.normpath(out)
        self._config["minimize_to_tray_on_close"] = self._tray_var.get()
        self._config["start_minimized"] = self._start_min_var.get()
        self._config["global_hotkey_enabled"] = self._hotkey_var.get()
        self._config["transcription_enabled"] = self._trans_on.get()
        if self._custom_var.get():
            self._config["transcription_model_dir"] = os.path.normpath(self._mdir_var.get().strip())
        else:
            self._config["transcription_model_dir"] = ""
        self._config["transcription_device"] = self._dev_var.get().strip() or "cpu"
        try:
            self._config["transcription_min_utterance_sec"] = max(1.0, float(self._min_u_var.get().strip() or "10"))
        except ValueError:
            self._config["transcription_min_utterance_sec"] = 10.0
        try:
            self._config["transcription_max_utterance_sec"] = max(
                5.0,
                float(self._max_u_var.get().strip() or "60"),
            )
        except ValueError:
            self._config["transcription_max_utterance_sec"] = 60.0
        try:
            self._config["transcription_end_silence_sec"] = max(0.1, float(self._sil_var.get().strip() or "0.8"))
        except ValueError:
            self._config["transcription_end_silence_sec"] = 0.8
        try:
            self._config["transcription_vad_aggressiveness"] = int(
                float(self._vad_var.get().strip() or "2")
            )
        except ValueError:
            self._config["transcription_vad_aggressiveness"] = 2
        self._config["transcription_vad_aggressiveness"] = max(
            0, min(3, int(self._config["transcription_vad_aggressiveness"]))
        )
        vb = self._vad_back_var.get().strip().lower()
        self._config["transcription_vad_backend"] = vb if vb in ("auto", "silero", "webrtc") else "auto"
        try:
            self._config["transcription_silero_threshold"] = max(
                0.05, min(0.95, float(self._silero_thr_var.get().strip() or "0.35"))
            )
        except ValueError:
            self._config["transcription_silero_threshold"] = 0.35
        try:
            self._config["transcription_vad_preroll_sec"] = max(
                0.0, min(3.0, float(self._preroll_var.get().strip() or "0.55"))
            )
        except ValueError:
            self._config["transcription_vad_preroll_sec"] = 0.55
        save_config(self._config)
        self._on_saved(self._config)
        self.destroy()
