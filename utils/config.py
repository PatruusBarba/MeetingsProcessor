"""JSON settings next to the application."""

from __future__ import annotations

import json
import os
from typing import Any

from utils.constants import app_dir

CONFIG_FILENAME = "settings.json"

DEFAULTS: dict[str, Any] = {
    "output_directory": None,
    "minimize_to_tray_on_close": True,
    "start_minimized": False,
    "global_hotkey_enabled": True,
    "last_input_device_id": None,
    "last_output_device_id": None,
    "transcription_enabled": False,
    "transcription_model_dir": "",
    "transcription_device": "cpu",
    "transcription_segment_sec": 3.0,
    "transcription_overlap_sec": 0.75,
}


def config_path() -> str:
    return os.path.join(app_dir(), CONFIG_FILENAME)


def load_config() -> dict[str, Any]:
    path = config_path()
    data = dict(DEFAULTS)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                data.update(stored)
                if "transcription_segment_sec" not in stored and stored.get("transcription_refresh_sec"):
                    try:
                        data["transcription_segment_sec"] = max(
                            1.5, float(stored["transcription_refresh_sec"]) * 6
                        )
                    except (TypeError, ValueError):
                        pass
        except (OSError, json.JSONDecodeError):
            pass
    if data.get("output_directory") is None:
        data["output_directory"] = os.path.join(app_dir(), "recordings")
    return data


def save_config(data: dict[str, Any]) -> None:
    path = config_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    to_store = {k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}
    if to_store.get("output_directory"):
        to_store["output_directory"] = os.path.normpath(to_store["output_directory"])
    if to_store.get("transcription_model_dir"):
        to_store["transcription_model_dir"] = os.path.normpath(str(to_store["transcription_model_dir"]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_store, f, indent=2)
