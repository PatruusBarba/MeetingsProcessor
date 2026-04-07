"""Headless / non-Windows UI smoke mode (no WASAPI, no real recording)."""

from __future__ import annotations

import os


def is_dev_ui() -> bool:
    v = os.environ.get("MEETING_RECORDER_DEV_UI", "").strip().lower()
    return v in ("1", "true", "yes", "on")
