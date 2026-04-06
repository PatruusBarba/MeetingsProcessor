"""
Live Parakeet TDT INT8 ONNX with VAD-gated utterances (not fixed 30 s cuts).

- Audio from the recorder is always buffered in parallel (decode never blocks capture).
- min_utterance_sec: only used to skip decode after long buffers with no speech (save CPU).
- Close utterance on end_silence_sec of trailing silence once there is enough audio to decode (~60 ms min; short phrases OK), or at max_utterance_sec (safety cap).
- Queue: ("phase", str), ("decode_start", {"sec": float}), ("decode_end", {}), ("append", str), None
"""

from __future__ import annotations

import array
import os
import queue
import threading
import time
from typing import Callable

import numpy as np

from audio.parakeet_onnx_runtime import ParakeetOnnxDecoder
from utils.speech_vad import create_stream_vad
from utils.transcription_log import log_line

SR = 16_000
# Minimum samples before we may close an utterance or run ONNX (~60 ms).
MIN_DECODE_SAMPLES = 960
# On recording stop, try final decode from this many samples (~30 ms).
MIN_TAIL_SAMPLES = 480
# Default if caller omits (normally from settings).
DEFAULT_VAD_PREROLL_SEC = 0.55


def _pcm16_to_f32_mono(mono_bytes: bytes) -> np.ndarray:
    if not mono_bytes:
        return np.array([], dtype=np.float32)
    a = array.array("h")
    a.frombytes(mono_bytes)
    x = np.asarray(a, dtype=np.float32) / 32768.0
    return np.clip(x, -1.0, 1.0)


def _resample_linear(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if x.size == 0 or src_sr == dst_sr:
        return x.astype(np.float32, copy=False)
    ratio = dst_sr / src_sr
    n_dst = max(1, int(len(x) * ratio))
    t_src = np.linspace(0.0, len(x) - 1, num=len(x), dtype=np.float64)
    t_dst = np.linspace(0.0, len(x) - 1, num=n_dst, dtype=np.float64)
    return np.interp(t_dst, t_src, x.astype(np.float64)).astype(np.float32)


def _merge_segment(accumulated: str, seg: str) -> str:
    a = accumulated.rstrip()
    seg = seg.strip()
    if not seg:
        return accumulated
    if not a:
        return seg
    max_l = min(len(a), len(seg), 240)
    for L in range(max_l, 3, -1):
        if a[-L:] == seg[:L]:
            rest = seg[L:].lstrip()
            return (a + (" " + rest if rest else "")).strip()
    return (a + " " + seg).strip()


def _buffer_rms(pcm: np.ndarray) -> float:
    if pcm.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))


class OnnxParakeetLiveTranscriberThread(threading.Thread):
    def __init__(
        self,
        audio_queue: queue.Queue,
        sample_rate_in: int,
        text_queue: queue.Queue,
        model_dir: str,
        device: str,
        min_utterance_sec: float,
        max_utterance_sec: float,
        end_silence_sec: float,
        vad_aggressiveness: int,
        vad_preroll_sec: float,
        vad_backend: str,
        silero_threshold: float,
        on_model_loading: Callable[[], None] | None,
        on_error: Callable[[str], None] | None,
        on_status: Callable[[str], None] | None,
    ) -> None:
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.sample_rate_in = sample_rate_in
        self.text_queue = text_queue
        self.model_dir = os.path.abspath(model_dir)
        self.device = device
        # Skip CPU work only after this much audio if VAD sees no speech (not required to end an utterance).
        self.min_skip_samples = max(int(float(min_utterance_sec) * SR), MIN_DECODE_SAMPLES)
        self.max_samples = max(
            int(float(max_utterance_sec) * SR),
            self.min_skip_samples + 8_000,
        )
        self.end_silence_sec = max(0.25, float(end_silence_sec))
        _pr = float(vad_preroll_sec) if vad_preroll_sec is not None else DEFAULT_VAD_PREROLL_SEC
        self.vad_preroll_sec = max(0.0, min(3.0, _pr))
        self.vad, self._vad_align_step, _vad_note = create_stream_vad(
            vad_backend,
            vad_aggressiveness,
            float(silero_threshold),
        )
        self._vad_backend_note = _vad_note
        self.on_model_loading = on_model_loading
        self.on_error = on_error
        self.on_status = on_status

    def _phase(self, msg: str) -> None:
        log_line(f"[transcriber] {msg}")
        try:
            self.text_queue.put_nowait(("phase", msg))
        except queue.Full:
            pass
        if self.on_status:
            self.on_status(msg)

    def _append_out(self, fragment: str) -> None:
        if not fragment:
            return
        try:
            self.text_queue.put_nowait(("append", fragment + " "))
        except queue.Full:
            pass

    def _decoding_start(self, audio_sec: float) -> None:
        try:
            self.text_queue.put_nowait(("decode_start", {"sec": float(max(0.0, audio_sec))}))
        except queue.Full:
            pass

    def _decoding_end(self) -> None:
        try:
            self.text_queue.put_nowait(("decode_end", {}))
        except queue.Full:
            pass

    def run(self) -> None:
        log_line(
            f"[transcriber] VAD utterances skip_if_silent={self.min_skip_samples/SR:.1f}s "
            f"max={self.max_samples/SR:.1f}s end_silence={self.end_silence_sec}s "
            f"preroll={self.vad_preroll_sec}s backend={getattr(self, '_vad_backend_note', '?')}"
        )

        def fail(msg: str) -> None:
            log_line(f"[transcriber] ERROR {msg}")
            self._phase(msg)
            if self.on_error:
                self.on_error(msg)
            try:
                self.text_queue.put_nowait(None)
            except queue.Full:
                pass

        try:
            if self.on_model_loading:
                self.on_model_loading()
            self._phase("Loading Parakeet ONNX…")
            decoder = ParakeetOnnxDecoder(self.model_dir, self.device)
        except FileNotFoundError as e:
            fail(f"Missing model file:\n{e}")
            return
        except Exception as e:
            fail(f"ONNX load failed: {e}")
            return

        self._phase(
            f"Listening — utterances by silence ({self._vad_backend_note}); "
            f"skip silent buffers ≥{self.min_skip_samples/SR:.0f}s…"
        )

        def run_decode_pcm(pcm: np.ndarray) -> str:
            return decoder.decode_pcm_mono_16k_f32(pcm)

        speech_buf = np.array([], dtype=np.float32)
        transcript = ""
        seg_i = 0

        def try_flush_utterance(force_tail: bool) -> None:
            nonlocal speech_buf, transcript, seg_i
            n = int(speech_buf.size)
            min_need = MIN_TAIL_SAMPLES if force_tail else MIN_DECODE_SAMPLES
            if n < min_need:
                return

            # Only drop long buffers that look like silence to BOTH VAD and RMS (avoids wiping real speech
            # when Silero/webrtc misclassifies quiet or mixed loopback audio).
            if n >= self.min_skip_samples and not self.vad.any_speech(speech_buf):
                if _buffer_rms(speech_buf) < 0.004:
                    log_line(f"[transcriber] skip silent buffer {n/SR:.1f}s (vad+rms)")
                    speech_buf = np.array([], dtype=np.float32)
                return

            trail_sil = self.vad.trailing_silence_seconds(speech_buf)
            hit_max = n >= self.max_samples
            hit_pause = (
                trail_sil >= self.end_silence_sec
                and n >= MIN_DECODE_SAMPLES
                and self.vad.any_speech(speech_buf)
            )

            if not force_tail and not hit_max and not hit_pause:
                return

            chunk: np.ndarray
            rest: np.ndarray

            if hit_max and not hit_pause and not force_tail:
                cut = self.max_samples
                chunk = speech_buf[:cut].copy()
                rest = speech_buf[cut:].copy()
            elif hit_pause and not force_tail:
                sil_samples = int(round(trail_sil * SR))
                sil_samples = min(sil_samples, n - MIN_DECODE_SAMPLES)
                step = self._vad_align_step
                sil_samples = max(0, (sil_samples // step) * step)
                cut = n - sil_samples
                if cut < MIN_DECODE_SAMPLES:
                    return
                chunk = speech_buf[:cut].copy()
                chunk = self.vad.trim_trailing_silence(chunk)
                rest = speech_buf[cut:].copy()
            else:
                chunk = speech_buf.copy()
                rest = np.array([], dtype=np.float32)

            chunk = self.vad.align_start_with_preroll(chunk, self.vad_preroll_sec)
            if chunk.size < MIN_DECODE_SAMPLES:
                speech_buf = np.concatenate([chunk, rest]) if chunk.size or rest.size else rest
                return

            self._decoding_start(float(chunk.size) / SR)
            t0 = time.perf_counter()
            try:
                text = run_decode_pcm(chunk)
            finally:
                self._decoding_end()
            dt = time.perf_counter() - t0
            seg_i += 1
            log_line(
                f"[transcriber] utt #{seg_i} samples={chunk.size} ({chunk.size/SR:.1f}s) {dt:.2f}s text_len={len(text)}"
            )
            if text:
                old = transcript
                transcript = _merge_segment(transcript, text)
                if transcript != old:
                    delta = transcript[len(old) :].lstrip() if transcript.startswith(old) else transcript
                    if delta:
                        self._append_out(delta)
            speech_buf = rest

        try:
            while True:
                try:
                    item = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    try_flush_utterance(force_tail=False)
                    continue
                if item is None:
                    self._phase("Final utterance…")
                    try_flush_utterance(force_tail=True)
                    if speech_buf.size >= MIN_TAIL_SAMPLES:
                        rms = _buffer_rms(speech_buf)
                        if self.vad.any_speech(speech_buf) or rms >= 0.004:
                            tail = self.vad.align_start_with_preroll(speech_buf, self.vad_preroll_sec)
                            self._decoding_start(float(tail.size) / SR)
                            t0 = time.perf_counter()
                            try:
                                text = run_decode_pcm(tail)
                            finally:
                                self._decoding_end()
                            log_line(f"[transcriber] final tail {time.perf_counter()-t0:.2f}s len={len(text)}")
                            if text:
                                old = transcript
                                transcript = _merge_segment(transcript, text)
                                if transcript != old:
                                    d = transcript[len(old) :].lstrip() if transcript.startswith(old) else transcript
                                    if d:
                                        self._append_out(d)
                    speech_buf = np.array([], dtype=np.float32)
                    break
                f32 = _pcm16_to_f32_mono(item)
                if self.sample_rate_in != SR:
                    f32 = _resample_linear(f32, self.sample_rate_in, SR)
                if f32.size:
                    speech_buf = np.concatenate([speech_buf, f32])
                try_flush_utterance(force_tail=False)
        except Exception as e:
            log_line(f"[transcriber] loop error {e}")
            if self.on_error:
                self.on_error(f"Transcription: {e}")
        finally:
            self._phase("Transcription finished.")
            log_line("[transcriber] exit")
            try:
                self.text_queue.put_nowait(None)
            except queue.Full:
                pass
