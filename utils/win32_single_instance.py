"""Single-instance mutex and bring existing window to foreground."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from utils.constants import APP_NAME, SINGLE_INSTANCE_MUTEX_NAME

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

ERROR_ALREADY_EXISTS = 183


def try_acquire_single_instance_mutex() -> bool:
    """
    Returns True if this process owns the app (first instance).
    Returns False if another instance is already running.
    """
    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    h = kernel32.CreateMutexW(None, True, SINGLE_INSTANCE_MUTEX_NAME)
    if not h:
        return True
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(h)
        return False
    return True


def bring_existing_window_to_front() -> None:
    """Best-effort: find our main window and activate it."""

    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    user32.EnumWindows.restype = wintypes.BOOL

    target: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if APP_NAME in title:
            target.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(callback, 0)
    if not target:
        return
    hwnd = target[0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
