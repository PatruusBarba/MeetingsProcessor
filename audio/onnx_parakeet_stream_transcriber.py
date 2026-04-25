"""
Live Parakeet TDT INT8 ONNX with VAD-gated utterances (not fixed 30 s cuts).

- Audio from the recorder is always buffered in parallel (decode never blocks capture).
- min_utterance_sec: only used to skip decode after long buffers with no speech (save CPU).
- Close utterance on end_silence_sec of trailing silence once there is enough audio to decode (~60 ms min; short words OK), or at max_utterance_sec (safety cap).
- Queue: ("phase", str), ("decode_start", {"sec": float}), ("decode_end", {}), ("append", str), None
"""

from __future__ import annotations

import array
from collections import deque
import os
import queue
import threading
import time
from typing import Callable

import numpy as np

from utils.speech_vad import FRAME_SAMPLES, UtteranceVAD
from utils.transcription_log import log_line

BLANK_ID = 8192
DURATIONS = [0, 1, 2, 3, 4]
N_DUR = len(DURATIONS)

SR = 16_000
# Minimum samples before we may close an utterance or run ONNX (~60 ms). Lower than 0.25 s so one short word still decodes.
MIN_DECODE_SAMPLES = 960
# On recording stop, try final decode from this many samples (~30 ms).
MIN_TAIL_SAMPLES = 480
# Waveform pad length for mel (longer pad helps very short utterances on this ONNX export).
MIN_WAVEFORM_PAD_SAMPLES = 16_000
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


def _load_vocab_txt(path: str) -> dict[int, str]:
    id_to_piece: dict[int, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            sp = line.rfind(" ")
            if sp < 0:
                continue
            piece = line[:sp]
            tid = int(line[sp + 1 :])
            id_to_piece[tid] = piece
    return id_to_piece


def _decode_ids(ids: list[int], id_to_piece: dict[int, str]) -> str:
    parts: list[str] = []
    for i in ids:
        p = id_to_piece.get(i, "")
        if p in ("<blk>", "<pad>", "<unk>"):
            continue
        parts.append(p)
    s = "".join(parts).replace("\u2581", " ")
    return " ".join(s.split()).strip()


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


def _ort_providers(device: str) -> list[str]:
    d = (device or "cpu").lower()
    if d == "cuda":
        try:
            import onnxruntime as ort

            if "CUDAExecutionProvider" in ort.get_available_providers():
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        except Exception:
            pass
    return ["CPUExecutionProvider"]


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
        self.vad = UtteranceVAD(aggressiveness=vad_aggressiveness)
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
            f"preroll={self.vad_preroll_sec}s"
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
            import onnxruntime as ort
        except ImportError:
            fail("Missing onnxruntime. pip install onnxruntime (or onnxruntime-gpu)")
            return

        mel_path = os.path.join(self.model_dir, "nemo128.onnx")
        enc_path = os.path.join(self.model_dir, "encoder-model.int8.onnx")
        dec_path = os.path.join(self.model_dir, "decoder_joint-model.int8.onnx")
        vocab_path = os.path.join(self.model_dir, "vocab.txt")

        self._phase("Checking model files…")
        for p in (mel_path, enc_path, dec_path, vocab_path):
            if not os.path.isfile(p):
                fail(f"Missing:\n{p}")
                return

        if self.on_model_loading:
            self.on_model_loading()

        self._phase("Reading vocabulary…")
        try:
            id_to_piece = _load_vocab_txt(vocab_path)
        except Exception as e:
            fail(f"vocab.txt: {e}")
            return

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = _ort_providers(self.device)
        self._phase(f"Loading ONNX (providers: {providers})…")

        try:
            t0 = time.perf_counter()
            mel_sess = ort.InferenceSession(mel_path, so, providers=providers)
            enc_sess = ort.InferenceSession(enc_path, so, providers=providers)
            dec_sess = ort.InferenceSession(dec_path, so, providers=providers)
            log_line(f"[transcriber] sessions ready {time.perf_counter()-t0:.1f}s")
        except Exception as e:
            fail(f"ONNX load failed: {e}")
            return

        vad_note = "webrtcvad" if self.vad._vad is not None else "energy VAD (pip install webrtcvad)"
        self._phase(
            f"Listening — utterances by silence ({vad_note}); "
            f"skip silent buffers ≥{self.min_skip_samples/SR:.0f}s…"
        )

        def tdt_greedy(enc_full: np.ndarray) -> list[int]:
            t = int(enc_full.shape[2])
            s1 = np.zeros((2, 1, 640), dtype=np.float32)
            s2 = np.zeros((2, 1, 640), dtype=np.float32)
            last_label = BLANK_ID
            tokens: list[int] = []
            time_idx = 0
            while time_idx < t:
                frame_start = time_idx
                f = enc_full[:, :, time_idx : time_idx + 1]
                sym = 0
                need_loop = True
                while need_loop and sym < 10:
                    targets = np.array([[last_label]], dtype=np.int32)
                    tl = np.array([1], dtype=np.int32)
                    out_logits, _pl, out_s1, out_s2 = dec_sess.run(
                        None,
                        {
                            "encoder_outputs": f,
                            "targets": targets,
                            "target_length": tl,
                            "input_states_1": s1,
                            "input_states_2": s2,
                        },
                    )
                    log = out_logits[0, 0, 0]
                    tok_logits = log[:-N_DUR]
                    dur_logits = log[-N_DUR:]
                    k = int(tok_logits.argmax())
                    dlp = dur_logits.astype(np.float64) - float(dur_logits.max())
                    ex = np.exp(dlp)
                    dlp = dlp - np.log(ex.sum() + 1e-12)
                    dk = int(dlp.argmax())
                    skip = DURATIONS[dk]
                    if k == BLANK_ID:
                        need_loop = False
                    else:
                        # Only update decoder states on non-blank tokens.
                        s1 = out_s1
                        s2 = out_s2
                        tokens.append(k)
                        last_label = k
                    sym += 1
                    time_idx += skip
                    need_loop = need_loop and (skip == 0)
                if time_idx <= frame_start:
                    time_idx = frame_start + 1
            return tokens

        def run_decode_pcm(pcm: np.ndarray) -> str:
            n = int(pcm.size)
            if n < 400:
                return ""
            actual_len = n
            pad_to = max(n, MIN_WAVEFORM_PAD_SAMPLES)
            if n < pad_to:
                pcm = np.concatenate([pcm, np.zeros(pad_to - n, dtype=np.float32)])
            wav = pcm.reshape(1, -1).astype(np.float32)
            wl = np.array([actual_len], dtype=np.int64)
            feat, fl = mel_sess.run(None, {"waveforms": wav, "waveforms_lens": wl})
            sig = feat.astype(np.float32)
            length = fl.astype(np.int64)
            enc_out, _elen = enc_sess.run(None, {"audio_signal": sig, "length": length})
            ids = tdt_greedy(enc_out)
            return _decode_ids(ids, id_to_piece)

        speech_chunks: deque[np.ndarray] = deque()
        speech_cache: np.ndarray | None = None
        speech_samples = 0
        speech_has_speech = False
        trailing_silence_frames = 0
        vad_carry = np.array([], dtype=np.float32)
        transcript = ""
        seg_i = 0
        last_backlog_log = 0.0

        def reset_speech_tracking() -> None:
            nonlocal speech_chunks, speech_cache, speech_samples, speech_has_speech, trailing_silence_frames, vad_carry
            speech_chunks.clear()
            speech_cache = None
            speech_samples = 0
            speech_has_speech = False
            trailing_silence_frames = 0
            vad_carry = np.array([], dtype=np.float32)

        def rescan_speech_tracking(pcm: np.ndarray) -> None:
            nonlocal speech_has_speech, trailing_silence_frames, vad_carry
            trailing_silence_frames = 0
            vad_carry = np.array([], dtype=np.float32)
            if pcm.size == 0:
                speech_has_speech = False
                return
            speech_has_speech = self.vad.any_speech(pcm)
            pos = 0
            n_scan = int(pcm.size)
            while pos + FRAME_SAMPLES <= n_scan:
                frame = pcm[pos : pos + FRAME_SAMPLES]
                if self.vad.frame_is_speech(frame):
                    trailing_silence_frames = 0
                    speech_has_speech = True
                else:
                    trailing_silence_frames += 1
                pos += FRAME_SAMPLES
            if pos < n_scan:
                vad_carry = pcm[pos:].copy()

        def set_speech_buffer(pcm: np.ndarray) -> None:
            nonlocal speech_cache, speech_samples
            reset_speech_tracking()
            if pcm.size:
                speech_chunks.append(pcm)
                speech_cache = pcm
                speech_samples = int(pcm.size)
                rescan_speech_tracking(pcm)

        def append_speech_chunk(pcm: np.ndarray) -> None:
            nonlocal speech_cache, speech_samples, speech_has_speech, trailing_silence_frames, vad_carry
            if pcm.size == 0:
                return
            speech_chunks.append(pcm)
            speech_cache = None
            speech_samples += int(pcm.size)
            scan = np.concatenate([vad_carry, pcm]) if vad_carry.size else pcm
            pos = 0
            n_scan = int(scan.size)
            while pos + FRAME_SAMPLES <= n_scan:
                frame = scan[pos : pos + FRAME_SAMPLES]
                if self.vad.frame_is_speech(frame):
                    trailing_silence_frames = 0
                    speech_has_speech = True
                else:
                    trailing_silence_frames += 1
                pos += FRAME_SAMPLES
            vad_carry = scan[pos:].copy() if pos < n_scan else np.array([], dtype=np.float32)
            if not speech_has_speech and self.vad.any_speech(pcm):
                speech_has_speech = True

        def materialize_speech() -> np.ndarray:
            nonlocal speech_cache
            if speech_cache is None:
                if not speech_chunks:
                    speech_cache = np.array([], dtype=np.float32)
                elif len(speech_chunks) == 1:
                    speech_cache = speech_chunks[0]
                else:
                    speech_cache = np.concatenate(list(speech_chunks))
            return speech_cache

        def try_flush_utterance(force_tail: bool) -> None:
            nonlocal transcript, seg_i
            n = speech_samples
            min_need = MIN_TAIL_SAMPLES if force_tail else MIN_DECODE_SAMPLES
            if n < min_need:
                return

            if n >= self.min_skip_samples and not speech_has_speech:
                log_line(f"[transcriber] skip silent buffer {n/SR:.1f}s")
                reset_speech_tracking()
                return

            trail_sil = trailing_silence_frames * (FRAME_SAMPLES / SR)
            hit_max = n >= self.max_samples
            hit_pause = (
                trail_sil >= self.end_silence_sec
                and n >= MIN_DECODE_SAMPLES
                and speech_has_speech
            )

            if not force_tail and not hit_max and not hit_pause:
                return

            speech_buf = materialize_speech()
            chunk: np.ndarray
            rest: np.ndarray

            if hit_max and not hit_pause:
                # Always chunk at max_samples, even when force_tail
                cut = self.max_samples
                chunk = speech_buf[:cut].copy()
                rest = speech_buf[cut:].copy()
            elif hit_pause and not force_tail:
                sil_samples = int(round(trail_sil * SR))
                sil_samples = min(sil_samples, n - MIN_DECODE_SAMPLES)
                sil_samples = max(0, (sil_samples // FRAME_SAMPLES) * FRAME_SAMPLES)
                cut = n - sil_samples
                if cut < MIN_DECODE_SAMPLES:
                    return
                chunk = speech_buf[:cut].copy()
                chunk = self.vad.trim_trailing_silence(chunk)
                rest = speech_buf[cut:].copy()
            else:
                chunk = speech_buf.copy()
                rest = np.array([], dtype=np.float32)

            chunk = self.vad.trim_leading_silence(chunk, max_trim_sec=5.0, keep_before_speech_sec=2.0)
            if chunk.size < MIN_DECODE_SAMPLES:
                set_speech_buffer(np.concatenate([chunk, rest]) if chunk.size or rest.size else rest)
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
            set_speech_buffer(rest)

        try:
            while True:
                try:
                    item = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    try_flush_utterance(force_tail=False)
                    continue
                if item is None:
                    # Drain remaining buffer in max_samples-sized chunks (capped iterations)
                    self._phase("Final utterance…")
                    max_iters = max(1, int(speech_samples / MIN_DECODE_SAMPLES) + 1)
                    for _ in range(max_iters):
                        if speech_samples < MIN_DECODE_SAMPLES:
                            break
                        prev_size = speech_samples
                        try_flush_utterance(force_tail=True)
                        if speech_samples >= prev_size:
                            break  # no progress — avoid infinite loop
                    reset_speech_tracking()
                    break
                f32 = _pcm16_to_f32_mono(item)
                if self.sample_rate_in != SR:
                    f32 = _resample_linear(f32, self.sample_rate_in, SR)
                if f32.size:
                    append_speech_chunk(f32)
                qmax = self.audio_queue.maxsize or 0
                if qmax and self.audio_queue.qsize() >= max(1, int(qmax * 0.75)):
                    now = time.monotonic()
                    if now - last_backlog_log >= 5.0:
                        last_backlog_log = now
                        log_line(
                            f"[transcriber] backlog high {self.audio_queue.qsize()}/{qmax} chunks"
                        )
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
