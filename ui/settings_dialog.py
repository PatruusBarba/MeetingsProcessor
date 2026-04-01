"""Settings Toplevel."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable

from utils.config import save_config


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
        ttk.Label(frm, text="Offline live transcription (faster-whisper)", font=("TkDefaultFont", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1

        self._trans_on = tk.BooleanVar(value=bool(self._config.get("transcription_enabled", False)))
        ttk.Checkbutton(
            frm,
            text="Enable live transcript during recording",
            variable=self._trans_on,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 2))
        row += 1

        ttk.Label(frm, text="Model:").grid(row=row, column=0, sticky="w")
        self._model_var = tk.StringVar(value=str(self._config.get("transcription_model") or "base"))
        model_cb = ttk.Combobox(
            frm,
            textvariable=self._model_var,
            values=("tiny", "base", "small", "medium", "large-v3"),
            width=18,
            state="readonly",
        )
        model_cb.grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Device:").grid(row=row, column=0, sticky="w")
        self._dev_var = tk.StringVar(value=str(self._config.get("transcription_device") or "cpu"))
        dev_cb = ttk.Combobox(
            frm,
            textvariable=self._dev_var,
            values=("cpu", "cuda"),
            width=18,
            state="readonly",
        )
        dev_cb.grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Compute type:").grid(row=row, column=0, sticky="w")
        self._ctype_var = tk.StringVar(value=str(self._config.get("transcription_compute_type") or "int8"))
        ctype_cb = ttk.Combobox(
            frm,
            textvariable=self._ctype_var,
            values=("int8", "float16", "float32", "int8_float16"),
            width=18,
            state="readonly",
        )
        ctype_cb.grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Language (empty = auto):").grid(row=row, column=0, sticky="w")
        self._lang_var = tk.StringVar(value=str(self._config.get("transcription_language") or ""))
        ttk.Entry(frm, textvariable=self._lang_var, width=22).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        hint = ttk.Label(
            frm,
            text="Tip: GPU needs PyTorch with CUDA; use float16 on cuda. Chunks ~3 s — not instant.",
            font=("TkDefaultFont", 8),
            foreground="gray",
            wraplength=420,
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

    def _browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self._dir_var.get() or os.path.expanduser("~"))
        if d:
            self._dir_var.set(d)

    def _save(self) -> None:
        out = self._dir_var.get().strip()
        if not out:
            out = self._config.get("output_directory") or ""
        self._config["output_directory"] = os.path.normpath(out)
        self._config["minimize_to_tray_on_close"] = self._tray_var.get()
        self._config["start_minimized"] = self._start_min_var.get()
        self._config["global_hotkey_enabled"] = self._hotkey_var.get()
        self._config["transcription_enabled"] = self._trans_on.get()
        self._config["transcription_model"] = self._model_var.get().strip() or "base"
        self._config["transcription_device"] = self._dev_var.get().strip() or "cpu"
        self._config["transcription_compute_type"] = self._ctype_var.get().strip() or "int8"
        self._config["transcription_language"] = self._lang_var.get().strip()
        save_config(self._config)
        self._on_saved(self._config)
        self.destroy()
