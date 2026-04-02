"""Append-only debug log next to the application (transcription & ONNX load steps)."""

from __future__ import annotations

import sys
from datetime import datetime

LOG_FILENAME = "transcription_debug.log"


def log_line(message: str) -> None:
    from utils.constants import app_dir

    import os

    path = os.path.join(app_dir(), LOG_FILENAME)
    line = f"{datetime.now().isoformat()} {message}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        try:
            print(line, end="", file=sys.stderr)
        except OSError:
            pass
