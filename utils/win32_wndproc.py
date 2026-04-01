"""Subclass tk HWND to receive WM_HOTKEY."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

GWLP_WNDPROC = -4

user32 = ctypes.windll.user32

# 64-bit window procedure addresses must use LONG_PTR, not default c_long (overflow on SetWindowLongPtrW).
if ctypes.sizeof(ctypes.c_void_p) == 8:
    LONG_PTR = ctypes.c_longlong
else:
    LONG_PTR = ctypes.c_long

LRESULT = ctypes.c_ssize_t if ctypes.sizeof(ctypes.c_void_p) == 8 else wintypes.LONG

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR

user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.SetWindowLongW.restype = wintypes.LONG

user32.CallWindowProcW.argtypes = [
    LONG_PTR,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallWindowProcW.restype = LRESULT

user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.DefWindowProcW.restype = LRESULT


class WndProcHook:
    def __init__(self, hwnd: int, on_hotkey) -> None:
        self.hwnd = hwnd
        self.on_hotkey = on_hotkey
        self._old_proc: int | None = None
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
            from utils.constants import WM_HOTKEY
            from utils.hotkeys import HOTKEY_ID

            if msg == WM_HOTKEY and wparam == HOTKEY_ID:
                self.on_hotkey()
                return 0
            if self._old_proc is None:
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            return user32.CallWindowProcW(
                LONG_PTR(self._old_proc),
                hwnd,
                msg,
                wparam,
                lparam,
            )

        self._new_proc = WNDPROC(wndproc)
        new_addr = ctypes.cast(self._new_proc, ctypes.c_void_p).value or 0

        if hasattr(user32, "SetWindowLongPtrW"):
            self._old_proc = int(
                user32.SetWindowLongPtrW(
                    wintypes.HWND(self.hwnd),
                    GWLP_WNDPROC,
                    LONG_PTR(new_addr),
                )
            )
        else:
            self._old_proc = int(
                user32.SetWindowLongW(
                    wintypes.HWND(self.hwnd),
                    GWLP_WNDPROC,
                    wintypes.LONG(new_addr),
                )
            )

    def uninstall(self) -> None:
        if self._old_proc is not None:
            if hasattr(user32, "SetWindowLongPtrW"):
                user32.SetWindowLongPtrW(
                    wintypes.HWND(self.hwnd),
                    GWLP_WNDPROC,
                    LONG_PTR(self._old_proc),
                )
            else:
                user32.SetWindowLongW(
                    wintypes.HWND(self.hwnd),
                    GWLP_WNDPROC,
                    wintypes.LONG(self._old_proc),
                )
            self._old_proc = None
        self._new_proc = None
