"""Incremental mono 16-bit WAV writer."""

from __future__ import annotations

import os
import wave


class MonoWavWriter:
    def __init__(self, path: str, sample_rate: int) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self._wf: wave.Wave_write | None = None

    def open(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        self._wf = wave.open(self.path, "wb")
        self._wf.setnchannels(1)
        self._wf.setsampwidth(2)
        self._wf.setframerate(self.sample_rate)

    def write_pcm(self, mono_int16: bytes) -> None:
        if self._wf and mono_int16:
            self._wf.writeframes(mono_int16)

    def close(self) -> None:
        if self._wf:
            self._wf.close()
            self._wf = None
