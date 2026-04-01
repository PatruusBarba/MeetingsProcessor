"""Global hotkey on Windows via RegisterHotKey."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from utils.constants import WM_HOTKEY, VK_R

if sys.platform != "win32":
    raise RuntimeError("Global hotkeys are only supported on Windows")

user32 = ctypes.windll.user32

MOD_NOREPEAT = 0x4000
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004

HOTKEY_ID = 1


class GlobalHotkey:
    def __init__(self) -> None:
        self._registered = False

    def register(self, hwnd: int | None = None) -> bool:
        if self._registered:
            return True
        target = hwnd or 0
        ok = user32.RegisterHotKey(
            wintypes.HWND(target),
            HOTKEY_ID,
            MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
            VK_R,
        )
        self._registered = bool(ok)
        return self._registered

    def unregister(self, hwnd: int | None = None) -> None:
        if not self._registered:
            return
        target = hwnd or 0
        user32.UnregisterHotKey(wintypes.HWND(target), HOTKEY_ID)
        self._registered = False

    @staticmethod
    def is_hotkey_message(msg: int, wparam: int) -> bool:
        return msg == WM_HOTKEY and wparam == HOTKEY_ID
