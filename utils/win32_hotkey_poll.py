"""
Detect Ctrl+Shift+R via GetAsyncKeyState from the tkinter main thread only.

Avoids RegisterHotKey + subclassed WndProc, which can crash Python when
combined with PyAudio threads (GIL / PyEval_RestoreThread).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":

    def poll_ctrl_shift_r_edge(was_down: bool) -> tuple[bool, bool]:
        return False, False

else:
    user32 = ctypes.windll.user32
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = wintypes.SHORT

    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    VK_R = 0x52


    def _key_down(vk: int) -> bool:
        return (user32.GetAsyncKeyState(vk) & 0x8000) != 0


    def poll_ctrl_shift_r_edge(was_down: bool) -> tuple[bool, bool]:
        combo = _key_down(VK_CONTROL) and _key_down(VK_SHIFT) and _key_down(VK_R)
        if combo and not was_down:
            return True, True
        if not combo:
            return False, False
        return False, True
