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

        ttk.Label(frm, text="Output directory:").grid(row=0, column=0, sticky="w")
        self._dir_var = tk.StringVar(value=self._config.get("output_directory") or "")
        ent = ttk.Entry(frm, textvariable=self._dir_var, width=50)
        ent.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(frm, text="Browse…", command=self._browse).grid(row=1, column=2, padx=(8, 0))

        self._tray_var = tk.BooleanVar(value=bool(self._config.get("minimize_to_tray_on_close", True)))
        ttk.Checkbutton(
            frm,
            text="Minimize to tray when closing window",
            variable=self._tray_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=4)

        self._start_min_var = tk.BooleanVar(value=bool(self._config.get("start_minimized", False)))
        ttk.Checkbutton(
            frm,
            text="Start minimized to tray",
            variable=self._start_min_var,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=4)

        self._hotkey_var = tk.BooleanVar(value=bool(self._config.get("global_hotkey_enabled", True)))
        ttk.Checkbutton(
            frm,
            text="Enable global hotkey (Ctrl+Shift+R)",
            variable=self._hotkey_var,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=4)

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=5, column=0, columnspan=3, pady=(16, 0))
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
        save_config(self._config)
        self._on_saved(self._config)
        self.destroy()
