"""
Meeting Audio Recorder — Windows 10 desktop app.
Run: python main.py
"""

from __future__ import annotations

import sys


def main() -> None:
    if sys.platform != "win32":
        print("This application requires Windows 10+ with WASAPI.", file=sys.stderr)
        sys.exit(1)

    from utils.win32_single_instance import bring_existing_window_to_front, try_acquire_single_instance_mutex

    if not try_acquire_single_instance_mutex():
        bring_existing_window_to_front()
        sys.exit(0)

    from ui.main_window import run_app

    run_app()


if __name__ == "__main__":
    main()
