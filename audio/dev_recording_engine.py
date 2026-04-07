"""Stub engine for MEETING_RECORDER_DEV_UI=1 — exercise UI without PyAudioWPatch."""

from __future__ import annotations

import random
import threading
import time
from typing import Callable


class DevRecordingEngine:
    """Mimics RecordingEngine surface used by MainWindow (no audio I/O)."""

    def __init__(self) -> None:
        self._stop_event: threading.Event | None = None
        self._paused_event: threading.Event | None = None
        self._level_pair: list[int] = [0, 0]
        self._error_box: list[tuple[str, str]] = []
        self._level_thread: threading.Thread | None = None

    def is_recording(self) -> bool:
        return self._stop_event is not None and not self._stop_event.is_set()

    def get_levels(self) -> tuple[int, int]:
        return int(self._level_pair[0]), int(self._level_pair[1])

    def get_errors(self) -> list[tuple[str, str]]:
        if not self._error_box:
            return []
        out = list(self._error_box)
        self._error_box.clear()
        return out

    def pause(self) -> None:
        if self._paused_event:
            self._paused_event.set()

    def resume(self) -> None:
        if self._paused_event:
            self._paused_event.clear()

    def is_paused(self) -> bool:
        return bool(self._paused_event and self._paused_event.is_set())

    def start(
        self,
        input_device_index: int,
        output_device_index: int,
        wav_path: str,
        mp3_path: str,
        on_disk_error: Callable[[str], None],
        on_convert_start: Callable[[], None],
        on_convert_done: Callable[[str], None],
        on_convert_error: Callable[[str], None],
        *,
        transcription_enabled: bool = False,
        transcription_text_queue=None,
        transcription_model_dir: str | None = "",
        transcription_device: str = "cpu",
        transcription_min_utterance_sec: float = 10.0,
        transcription_max_utterance_sec: float = 60.0,
        transcription_end_silence_sec: float = 0.8,
        transcription_vad_aggressiveness: int = 2,
        transcription_vad_preroll_sec: float = 0.55,
        transcription_vad_backend: str = "webrtc",
        transcription_silero_threshold: float = 0.35,
        on_transcription_model_loading=None,
        on_transcription_error=None,
        on_transcription_status=None,
    ) -> tuple[bool, str | None]:
        _ = (
            input_device_index,
            output_device_index,
            wav_path,
            mp3_path,
            on_disk_error,
            transcription_enabled,
            transcription_text_queue,
            transcription_model_dir,
            transcription_device,
            transcription_min_utterance_sec,
            transcription_max_utterance_sec,
            transcription_end_silence_sec,
            transcription_vad_aggressiveness,
            transcription_vad_preroll_sec,
            transcription_vad_backend,
            transcription_silero_threshold,
            on_transcription_model_loading,
            on_transcription_error,
            on_transcription_status,
        )
        self._stop_event = threading.Event()
        self._paused_event = threading.Event()

        def tick_levels() -> None:
            while self._stop_event and not self._stop_event.is_set():
                if self._paused_event and self._paused_event.is_set():
                    self._level_pair[0] = 0
                    self._level_pair[1] = 0
                else:
                    self._level_pair[0] = random.randint(15, 85)
                    self._level_pair[1] = random.randint(10, 70)
                time.sleep(0.12)

        self._level_thread = threading.Thread(target=tick_levels, daemon=True)
        self._level_thread.start()
        self._mp3_path = mp3_path
        self._on_convert_start = on_convert_start
        self._on_convert_done = on_convert_done
        return True, None

    def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._level_thread and self._level_thread.is_alive():
            self._level_thread.join(timeout=2.0)
        self._level_thread = None
        self._stop_event = None
        self._paused_event = None
        self._level_pair = [0, 0]

        mp3 = getattr(self, "_mp3_path", "dev_stub.mp3")
        start_cb = getattr(self, "_on_convert_start", None)
        done_cb = getattr(self, "_on_convert_done", None)

        def fake_convert() -> None:
            if start_cb:
                start_cb()
            time.sleep(0.45)
            if done_cb:
                done_cb(mp3)

        threading.Thread(target=fake_convert, daemon=True).start()
