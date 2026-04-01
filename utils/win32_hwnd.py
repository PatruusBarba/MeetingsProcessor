"""Tkinter window handle for Win32 APIs."""

from __future__ import annotations

import ctypes

GA_ROOT = 2


def tk_root_hwnd(widget) -> int:
    widget.update_idletasks()
    child = widget.winfo_id()
    return int(ctypes.windll.user32.GetAncestor(child, GA_ROOT))
