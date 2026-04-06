"""Optional Silero VAD (silero-vad-lite) for 16 kHz float32 mono PCM."""

from __future__ import annotations

import numpy as np

_ENERGY_RMS = 0.012


def silero_available() -> bool:
    try:
        from silero_vad_lite import SileroVAD  # noqa: F401

        return True
    except Exception:
        return False


class SileroUtteranceVAD:
    """512-sample windows at 16 kHz; probabilities 0..1."""

    def __init__(self, threshold: float = 0.35) -> None:
        from silero_vad_lite import SileroVAD

        self._vad = SileroVAD(16000)
        self.w = int(self._vad.window_size_samples)
        self.threshold = float(np.clip(threshold, 0.05, 0.95))

    def _prob(self, chunk: np.ndarray) -> float:
        x = np.ascontiguousarray(chunk, dtype=np.float32)
        return float(self._vad.process(memoryview(x)))

    def frame_prob(self, pcm: np.ndarray, start: int) -> float | None:
        if start < 0 or start + self.w > int(pcm.size):
            return None
        return self._prob(pcm[start : start + self.w])

    def any_speech(self, pcm: np.ndarray) -> bool:
        n = int(pcm.size)
        if n < self.w:
            return _short_energy_speech(pcm)
        for i in range(0, n - self.w + 1, self.w):
            if self._prob(pcm[i : i + self.w]) >= self.threshold:
                return True
        return False

    def trailing_silence_seconds(self, pcm: np.ndarray) -> float:
        n = int(pcm.size)
        w = self.w
        if n < w:
            return 0.0
        silent = 0
        pos = n
        while pos >= w:
            start = pos - w
            if self._prob(pcm[start:pos]) >= self.threshold:
                break
            silent += 1
            pos = start
        return silent * (w / 16000.0)

    def trim_trailing_silence(self, pcm: np.ndarray) -> np.ndarray:
        n = int(pcm.size)
        w = self.w
        if n < w:
            return pcm
        pos = n
        while pos >= w:
            if self._prob(pcm[pos - w : pos]) >= self.threshold:
                return pcm[:pos]
            pos -= w
        return pcm[:0]

    def first_speech_window_start(self, pcm: np.ndarray) -> int | None:
        n = int(pcm.size)
        w = self.w
        if n < w:
            return None
        for i in range(0, n - w + 1, w):
            if self._prob(pcm[i : i + w]) >= self.threshold:
                return i
        return None

    def first_energy_onset_sample(self, pcm: np.ndarray, hop_samples: int | None = None) -> int | None:
        n = int(pcm.size)
        w = self.w
        if n < w:
            return None
        hop = max(w // 4, int(hop_samples or (w // 2)))
        thr = _ENERGY_RMS * 0.4
        for i in range(0, n - w + 1, hop):
            frame = pcm[i : i + w]
            rms = float(np.sqrt(np.mean(frame * frame)))
            if rms >= thr:
                return i
        return None

    def first_speech_onset_sample(self, pcm: np.ndarray) -> int | None:
        e = self.first_energy_onset_sample(pcm)
        s = self.first_speech_window_start(pcm)
        if e is None:
            return s
        if s is None:
            return e
        return min(e, s)

    def align_start_with_preroll(self, pcm: np.ndarray, preroll_sec: float) -> np.ndarray:
        n = int(pcm.size)
        if n == 0:
            return pcm
        first = self.first_speech_onset_sample(pcm)
        if first is None:
            return pcm
        pr = int(max(0.0, float(preroll_sec)) * 16000)
        start = max(0, first - pr)
        return pcm[start:]


def _short_energy_speech(pcm: np.ndarray) -> bool:
    n = int(pcm.size)
    if n <= 80:
        return False
    rms = float(np.sqrt(np.mean(pcm * pcm)))
    return rms >= _ENERGY_RMS * 1.1
