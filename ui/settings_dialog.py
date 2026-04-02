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
        ttk.Label(
            frm,
            text="Offline live transcription (NVIDIA Parakeet TDT V3, NeMo)",
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

        ttk.Label(frm, text="Pretrained name / HF id:").grid(row=row, column=0, sticky="w")
        self._pretrained_var = tk.StringVar(
            value=str(self._config.get("transcription_pretrained_name") or "nvidia/parakeet-tdt-0.6b-v3")
        )
        ttk.Entry(frm, textvariable=self._pretrained_var, width=42).grid(row=row, column=1, sticky="ew", padx=(8, 0))
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

        ttk.Label(frm, text="Torch dtype:").grid(row=row, column=0, sticky="w")
        self._dtype_var = tk.StringVar(value=str(self._config.get("transcription_torch_dtype") or "float32"))
        dtype_cb = ttk.Combobox(
            frm,
            textvariable=self._dtype_var,
            values=("float32", "float16", "bfloat16"),
            width=18,
            state="readonly",
        )
        dtype_cb.grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Stream chunk (sec):").grid(row=row, column=0, sticky="w")
        self._chunk_var = tk.StringVar(value=str(self._config.get("transcription_chunk_secs", 2.0)))
        ttk.Entry(frm, textvariable=self._chunk_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Left context (sec):").grid(row=row, column=0, sticky="w")
        self._left_var = tk.StringVar(value=str(self._config.get("transcription_left_context_secs", 10.0)))
        ttk.Entry(frm, textvariable=self._left_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Right context (sec):").grid(row=row, column=0, sticky="w")
        self._right_var = tk.StringVar(value=str(self._config.get("transcription_right_context_secs", 2.0)))
        ttk.Entry(frm, textvariable=self._right_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        hint = ttk.Label(
            frm,
            text=(
                "Uses NeMo’s official RNNT streaming buffer (see NVIDIA NeMo "
                "speech_to_text_streaming_infer_rnnt). Russian is supported; ~0.6B model — prefer GPU. "
                "Install: pip install 'nemo_toolkit[asr]'"
            ),
            font=("TkDefaultFont", 8),
            foreground="gray",
            wraplength=440,
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
        self._config["transcription_pretrained_name"] = self._pretrained_var.get().strip() or "nvidia/parakeet-tdt-0.6b-v3"
        self._config["transcription_device"] = self._dev_var.get().strip() or "cpu"
        self._config["transcription_torch_dtype"] = self._dtype_var.get().strip() or "float32"
        try:
            self._config["transcription_chunk_secs"] = float(self._chunk_var.get().strip() or "2")
        except ValueError:
            self._config["transcription_chunk_secs"] = 2.0
        try:
            self._config["transcription_left_context_secs"] = float(self._left_var.get().strip() or "10")
        except ValueError:
            self._config["transcription_left_context_secs"] = 10.0
        try:
            self._config["transcription_right_context_secs"] = float(self._right_var.get().strip() or "2")
        except ValueError:
            self._config["transcription_right_context_secs"] = 2.0
        save_config(self._config)
        self._on_saved(self._config)
        self.destroy()
