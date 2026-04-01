"""Subclass tk HWND to receive WM_HOTKEY."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

GWLP_WNDPROC = -4

user32 = ctypes.windll.user32
LRESULT = ctypes.c_ssize_t if ctypes.sizeof(ctypes.c_void_p) == 8 else wintypes.LONG


class WndProcHook:
    def __init__(self, hwnd: int, on_hotkey) -> None:
        self.hwnd = hwnd
        self.on_hotkey = on_hotkey
        self._old_proc = None
        self._new_proc = None

    def install(self) -> None:
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        def wndproc(hwnd, msg, wparam, lparam):
            from utils.hotkeys import HOTKEY_ID
            from utils.constants import WM_HOTKEY

            if msg == WM_HOTKEY and wparam == HOTKEY_ID:
                self.on_hotkey()
                return 0
            prev = ctypes.c_void_p(self._old_proc)
            return user32.CallWindowProcW(prev, hwnd, msg, wparam, lparam)

        self._new_proc = WNDPROC(wndproc)
        if hasattr(user32, "SetWindowLongPtrW"):
            self._old_proc = user32.SetWindowLongPtrW(
                wintypes.HWND(self.hwnd),
                GWLP_WNDPROC,
                ctypes.cast(self._new_proc, ctypes.c_void_p).value or 0,
            )
        else:
            self._old_proc = user32.SetWindowLongW(
                wintypes.HWND(self.hwnd),
                GWLP_WNDPROC,
                ctypes.cast(self._new_proc, ctypes.c_void_p).value or 0,
            )

    def uninstall(self) -> None:
        if self._old_proc is not None:
            if hasattr(user32, "SetWindowLongPtrW"):
                user32.SetWindowLongPtrW(
                    wintypes.HWND(self.hwnd),
                    GWLP_WNDPROC,
                    self._old_proc,
                )
            else:
                user32.SetWindowLongW(
                    wintypes.HWND(self.hwnd),
                    GWLP_WNDPROC,
                    self._old_proc,
                )
            self._old_proc = None
        self._new_proc = None
