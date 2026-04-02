"""Download / verify / remove Parakeet ONNX bundle next to the application."""

from __future__ import annotations

import os
import shutil
import threading
from typing import Callable

from utils.constants import PARAKEET_ONNX_REPO_ID, bundled_parakeet_onnx_dir

REQUIRED_FILES = (
    "nemo128.onnx",
    "encoder-model.int8.onnx",
    "decoder_joint-model.int8.onnx",
    "vocab.txt",
)


def resolve_transcription_model_dir(config_dir_value: str | None) -> str:
    """Empty config → bundled folder next to exe; otherwise custom path."""
    v = (config_dir_value or "").strip()
    if v:
        return os.path.normpath(v)
    return bundled_parakeet_onnx_dir()


def is_bundle_complete(model_dir: str) -> bool:
    if not model_dir or not os.path.isdir(model_dir):
        return False
    return all(os.path.isfile(os.path.join(model_dir, f)) for f in REQUIRED_FILES)


def download_parakeet_bundle(
    on_status: Callable[[str], None],
    on_done: Callable[[bool, str], None],
    dest_dir: str | None = None,
) -> None:
    """
    Run in a background thread. on_done(ok, message).
    """

    def work() -> None:
        target = os.path.normpath(dest_dir) if dest_dir else bundled_parakeet_onnx_dir()
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            on_done(False, "Install huggingface_hub: pip install huggingface_hub")
            return

        on_status("Downloading Parakeet ONNX from Hugging Face… (~670 MB)")
        try:
            os.makedirs(target, exist_ok=True)
            snapshot_download(
                repo_id=PARAKEET_ONNX_REPO_ID,
                local_dir=target,
                local_dir_use_symlinks=False,
            )
        except Exception as e:
            on_done(False, f"Download failed: {e}")
            return

        if not is_bundle_complete(target):
            on_done(False, "Download finished but required files are missing.")
            return
        on_status("Model ready.")
        on_done(True, target)

    threading.Thread(target=work, daemon=True).start()


def delete_bundled_model(on_done: Callable[[bool, str], None]) -> None:
    """Remove only the app-bundled folder (next to exe)."""

    def work() -> None:
        p = bundled_parakeet_onnx_dir()
        if not os.path.isdir(p):
            on_done(True, "Nothing to remove.")
            return
        try:
            shutil.rmtree(p)
            on_done(True, "Model files removed.")
        except OSError as e:
            on_done(False, f"Could not delete: {e}")

    threading.Thread(target=work, daemon=True).start()
