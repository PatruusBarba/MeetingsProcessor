"""Voice activity helpers for 16 kHz mono float32 PCM (webrtcvad + energy fallback)."""

from __future__ import annotations

import numpy as np

FRAME_SAMPLES = 480  # 30 ms @ 16 kHz (webrtcvad requirement)


def _f32_to_i16_bytes(chunk: np.ndarray) -> bytes:
    x = np.clip(chunk.astype(np.float64) * 32768.0, -32768, 32767).astype(np.int16)
    return x.tobytes()


def _energy_speech(frame_f32: np.ndarray, rms_threshold: float = 0.012) -> bool:
    if frame_f32.size < FRAME_SAMPLES:
        return False
    rms = float(np.sqrt(np.mean(frame_f32 * frame_f32)))
    return rms >= rms_threshold


class UtteranceVAD:
    def __init__(self, aggressiveness: int = 2, energy_rms: float = 0.012) -> None:
        self._vad = None
        self._energy_rms = energy_rms
        try:
            import webrtcvad

            self._vad = webrtcvad.Vad(int(np.clip(aggressiveness, 0, 3)))
        except Exception:
            pass

    def frame_is_speech(self, frame_f32: np.ndarray) -> bool:
        if frame_f32.size != FRAME_SAMPLES:
            return False
        if self._vad is not None:
            try:
                return bool(self._vad.is_speech(_f32_to_i16_bytes(frame_f32), 16000))
            except Exception:
                pass
        return _energy_speech(frame_f32, self._energy_rms)

    def any_speech(self, pcm: np.ndarray) -> bool:
        n = int(pcm.size)
        if n < FRAME_SAMPLES:
            return _energy_speech(pcm, self._energy_rms * 1.5) if n > 80 else False
        for i in range(0, n - FRAME_SAMPLES + 1, FRAME_SAMPLES):
            if self.frame_is_speech(pcm[i : i + FRAME_SAMPLES]):
                return True
        tail = n % FRAME_SAMPLES
        if tail > 160:
            return _energy_speech(pcm[n - tail :], self._energy_rms * 1.5)
        return False

    def trailing_silence_seconds(self, pcm: np.ndarray) -> float:
        """Length of trailing silence from the end (coarse, 30 ms frames)."""
        n = int(pcm.size)
        if n < FRAME_SAMPLES:
            return 0.0
        silent_frames = 0
        pos = n
        while pos >= FRAME_SAMPLES:
            start = pos - FRAME_SAMPLES
            frame = pcm[start:pos]
            if self.frame_is_speech(frame):
                break
            silent_frames += 1
            pos = start
        return silent_frames * (FRAME_SAMPLES / 16000.0)

    def trim_trailing_silence(self, pcm: np.ndarray) -> np.ndarray:
        """Drop silent 30 ms frames from the end; return prefix up to last speech frame."""
        n = int(pcm.size)
        if n < FRAME_SAMPLES:
            return pcm
        pos = n
        while pos >= FRAME_SAMPLES:
            start = pos - FRAME_SAMPLES
            if self.frame_is_speech(pcm[start:pos]):
                return pcm[:pos]
            pos = start
        return pcm[:0]

    def trim_leading_silence(self, pcm: np.ndarray, max_trim_sec: float = 2.0) -> np.ndarray:
        """Drop leading silent frames up to max_trim_sec."""
        n = int(pcm.size)
        if n < FRAME_SAMPLES:
            return pcm
        max_frames = int(max_trim_sec * 16000 / FRAME_SAMPLES)
        dropped = 0
        pos = 0
        while pos + FRAME_SAMPLES <= n and dropped < max_frames:
            if self.frame_is_speech(pcm[pos : pos + FRAME_SAMPLES]):
                break
            pos += FRAME_SAMPLES
            dropped += 1
        return pcm[pos:] if pos > 0 else pcm

    def first_speech_frame_start(self, pcm: np.ndarray) -> int | None:
        """Sample index of the first full 30 ms frame classified as speech, or None."""
        n = int(pcm.size)
        if n < FRAME_SAMPLES:
            return None
        for i in range(0, n - FRAME_SAMPLES + 1, FRAME_SAMPLES):
            if self.frame_is_speech(pcm[i : i + FRAME_SAMPLES]):
                return i
        return None

    def first_energy_onset_sample(self, pcm: np.ndarray, hop_samples: int = 160) -> int | None:
        """Earlier weak-onset detection (10 ms steps); webrtcvad often lags real speech start."""
        n = int(pcm.size)
        if n < FRAME_SAMPLES:
            return None
        hop = max(80, int(hop_samples))
        thr = float(self._energy_rms) * 0.5
        for i in range(0, n - FRAME_SAMPLES + 1, hop):
            frame = pcm[i : i + FRAME_SAMPLES]
            rms = float(np.sqrt(np.mean(frame * frame)))
            if rms >= thr:
                return i
        return None

    def first_speech_onset_sample(self, pcm: np.ndarray) -> int | None:
        """Earliest of fine energy onset and VAD speech frame (whichever comes first)."""
        e = self.first_energy_onset_sample(pcm)
        v = self.first_speech_frame_start(pcm)
        if e is None:
            return v
        if v is None:
            return e
        return min(e, v)

    def align_start_with_preroll(self, pcm: np.ndarray, preroll_sec: float) -> np.ndarray:
        """
        Keep audio from (first detected speech onset minus preroll). Energy scan catches weak
        syllable starts before webrtcvad; preroll covers remaining attack delay.
        """
        n = int(pcm.size)
        if n == 0:
            return pcm
        first = self.first_speech_onset_sample(pcm)
        if first is None:
            return pcm
        pr = int(max(0.0, float(preroll_sec)) * 16000)
        start = max(0, first - pr)
        return pcm[start:]
