"""
Meeting Audio Recorder — Windows 10 desktop app.
Run: python main.py

UI-only smoke test on Linux/macOS (no audio):
  MEETING_RECORDER_DEV_UI=1 python main.py
  python main.py --dev-ui
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--dev-ui",
        action="store_true",
        help="Open Tk UI without Windows/WASAPI (stub devices + fake record flow). Sets MEETING_RECORDER_DEV_UI=1.",
    )
    args, _unknown = parser.parse_known_args()
    if args.dev_ui:
        os.environ["MEETING_RECORDER_DEV_UI"] = "1"

    from utils.dev_mode import is_dev_ui

    if sys.platform != "win32" and not is_dev_ui():
        print("This application requires Windows 10+ with WASAPI.", file=sys.stderr)
        print("Hint: MEETING_RECORDER_DEV_UI=1 or python main.py --dev-ui  (Tk only, no real recording).", file=sys.stderr)
        sys.exit(1)

    if is_dev_ui():
        from ui.main_window import run_app

        run_app()
        return

    from utils.win32_single_instance import bring_existing_window_to_front, try_acquire_single_instance_mutex

    if not try_acquire_single_instance_mutex():
        bring_existing_window_to_front()
        sys.exit(0)

    from ui.main_window import run_app

    run_app()


if __name__ == "__main__":
    main()
