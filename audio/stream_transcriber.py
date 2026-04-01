"""Offline live transcription with faster-whisper (mono PCM chunks in, text lines out)."""

from __future__ import annotations

import array
import queue
import threading
from typing import Callable

# Chunk length at input sample rate (seconds) — balance latency vs accuracy
CHUNK_SECONDS = 3.0
# Minimum audio to send to Whisper on flush (seconds)
MIN_FLUSH_SECONDS = 0.4
WHISPER_SAMPLE_RATE = 16_000


def _pcm16_bytes_to_float32(mono_bytes: bytes):
    import numpy as np

    if not mono_bytes:
        return np.array([], dtype=np.float32)
    a = array.array("h")
    a.frombytes(mono_bytes)
    x = np.asarray(a, dtype=np.float32) / 32768.0
    return np.clip(x, -1.0, 1.0)


def _resample_linear(x, src_sr: int, dst_sr: int):
    import numpy as np

    if x.size == 0 or src_sr == dst_sr:
        return x.astype(np.float32, copy=False)
    ratio = dst_sr / src_sr
    n_dst = max(1, int(len(x) * ratio))
    t_src = np.linspace(0.0, len(x) - 1, num=len(x), dtype=np.float64)
    t_dst = np.linspace(0.0, len(x) - 1, num=n_dst, dtype=np.float64)
    return np.interp(t_dst, t_src, x.astype(np.float64)).astype(np.float32)


class LiveTranscriberThread(threading.Thread):
    """
    Consumes mono int16 PCM (same rate as recording) from audio_queue.
    Puts decoded text lines into text_queue (str). None sentinel ends input.
    """

    def __init__(
        self,
        audio_queue: queue.Queue,
        sample_rate: int,
        text_queue: queue.Queue,
        model_size: str,
        device: str,
        compute_type: str,
        language: str | None,
        on_model_loading: Callable[[], None] | None,
        on_error: Callable[[str], None] | None,
    ) -> None:
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.sample_rate = sample_rate
        self.text_queue = text_queue
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language if language else None
        self.on_model_loading = on_model_loading
        self.on_error = on_error

    def run(self) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            if self.on_error:
                self.on_error(
                    "faster-whisper is not installed. Run: pip install faster-whisper"
                )
            return

        if self.on_model_loading:
            self.on_model_loading()

        try:
            model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        except Exception as e:
            if self.on_error:
                self.on_error(f"Failed to load Whisper model: {e}")
            return

        min_bytes = int(self.sample_rate * 2 * CHUNK_SECONDS)
        min_flush_bytes = int(self.sample_rate * 2 * MIN_FLUSH_SECONDS)
        buf = bytearray()

        def transcribe_bytes(pcm: bytes) -> None:
            if len(pcm) < min_flush_bytes:
                return
            f32 = _pcm16_bytes_to_float32(pcm)
            audio_16k = _resample_linear(f32, self.sample_rate, WHISPER_SAMPLE_RATE)
            if audio_16k.size < 800:
                return
            try:
                segments, _info = model.transcribe(
                    audio_16k,
                    language=self.language,
                    task="transcribe",
                    beam_size=1,
                    vad_filter=True,
                    without_timestamps=True,
                )
                parts: list[str] = []
                for seg in segments:
                    t = (seg.text or "").strip()
                    if t:
                        parts.append(t)
                line = " ".join(parts).strip()
                if line:
                    self.text_queue.put(line)
            except Exception as e:
                if self.on_error:
                    self.on_error(f"Transcription error: {e}")

        while True:
            try:
                item = self.audio_queue.get(timeout=0.15)
            except queue.Empty:
                continue
            if item is None:
                if len(buf) >= min_flush_bytes:
                    transcribe_bytes(bytes(buf))
                buf.clear()
                break
            buf.extend(item)
            while len(buf) >= min_bytes:
                chunk = bytes(buf[:min_bytes])
                del buf[:min_bytes]
                transcribe_bytes(chunk)

        self.text_queue.put(None)
