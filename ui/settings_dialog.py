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
            text="Live transcription (Parakeet TDT V3 INT8 ONNX — local folder)",
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

        ttk.Label(frm, text="ONNX model folder:").grid(row=row, column=0, sticky="nw")
        self._mdir_var = tk.StringVar(value=str(self._config.get("transcription_model_dir") or ""))
        mdir_ent = ttk.Entry(frm, textvariable=self._mdir_var, width=48)
        mdir_ent.grid(row=row, column=1, sticky="ew", padx=(8, 0))
        ttk.Button(frm, text="Browse…", command=self._browse_model).grid(row=row, column=2, padx=(8, 0))
        row += 1

        ttk.Label(frm, text="Must contain: nemo128.onnx, encoder-model.int8.onnx, decoder_joint-model.int8.onnx, vocab.txt", font=("TkDefaultFont", 8), foreground="gray", wraplength=460).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
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

        ttk.Label(frm, text="UI refresh (sec):").grid(row=row, column=0, sticky="w")
        self._ref_var = tk.StringVar(value=str(self._config.get("transcription_refresh_sec", 0.35)))
        ttk.Entry(frm, textvariable=self._ref_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1

        hint = ttk.Label(
            frm,
            text=(
                "Uses ONNX Runtime only (no NeMo, no 2.5 GB download). "
                "Same export as smcleod/parakeet-tdt-0.6b-v3-int8 on Hugging Face. "
                "For GPU: pip install onnxruntime-gpu."
            ),
            font=("TkDefaultFont", 8),
            foreground="gray",
            wraplength=460,
        )
        hint.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        row += 1

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=row, column=0, columnspan=3, pady=(16, 0))
        ttk.Button(btn_frm, text="Save", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frm, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=4)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

    def _browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self._dir_var.get() or os.path.expanduser("~"))
        if d:
            self._dir_var.set(d)

    def _browse_model(self) -> None:
        d = filedialog.askdirectory(initialdir=self._mdir_var.get() or os.path.expanduser("~"))
        if d:
            self._mdir_var.set(d)

    def _save(self) -> None:
        out = self._dir_var.get().strip()
        if not out:
            out = self._config.get("output_directory") or ""
        self._config["output_directory"] = os.path.normpath(out)
        self._config["minimize_to_tray_on_close"] = self._tray_var.get()
        self._config["start_minimized"] = self._start_min_var.get()
        self._config["global_hotkey_enabled"] = self._hotkey_var.get()
        self._config["transcription_enabled"] = self._trans_on.get()
        self._config["transcription_model_dir"] = self._mdir_var.get().strip()
        self._config["transcription_device"] = self._dev_var.get().strip() or "cpu"
        try:
            self._config["transcription_refresh_sec"] = float(self._ref_var.get().strip() or "0.35")
        except ValueError:
            self._config["transcription_refresh_sec"] = 0.35
        save_config(self._config)
        self._on_saved(self._config)
        self.destroy()
