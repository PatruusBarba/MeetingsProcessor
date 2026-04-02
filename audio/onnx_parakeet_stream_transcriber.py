"""
Live Parakeet TDT INT8 ONNX — sliding-window segments (standard streaming ASR).

Re-decode on the entire growing buffer fails on long audio with this export (log: full_len=0).
We decode fixed-length 16 kHz windows with overlap and merge text — same idea as chunked
inference in NeMo / live captioning.

Queue: ("phase", str), ("append", str), None
"""

from __future__ import annotations

import array
import os
import queue
import threading
import time
from typing import Callable

import numpy as np

from utils.transcription_log import log_line

BLANK_ID = 8192
DURATIONS = [0, 1, 2, 3, 4]
N_DUR = len(DURATIONS)

SR = 16_000
MIN_DECODE_SAMPLES = 4_000  # 0.25 s minimum for a tail decode


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
    """Join new chunk text; strip duplicate overlap at boundary (same audio in two windows)."""
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
        segment_sec: float,
        overlap_sec: float,
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
        self.chunk_samples = max(int(float(segment_sec) * SR), 8000)
        ov = max(0.0, min(float(overlap_sec), float(segment_sec) * 0.45))
        self.advance_samples = max(self.chunk_samples // 4, self.chunk_samples - int(ov * SR))
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

    def run(self) -> None:
        log_line(
            f"[transcriber] start sliding window chunk={self.chunk_samples} adv={self.advance_samples} ({self.chunk_samples/SR:.1f}s)"
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

        self._phase(
            f"Listening — {self.chunk_samples/SR:.1f}s segments, overlap ~{(self.chunk_samples-self.advance_samples)/SR:.1f}s…"
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
                    logits, _pl, s1, s2 = dec_sess.run(
                        None,
                        {
                            "encoder_outputs": f,
                            "targets": targets,
                            "target_length": tl,
                            "input_states_1": s1,
                            "input_states_2": s2,
                        },
                    )
                    log = logits[0, 0, 0]
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
            if n < 800:
                return ""
            if n < self.chunk_samples:
                pad = np.zeros(self.chunk_samples - n, dtype=np.float32)
                pcm = np.concatenate([pcm, pad])
            wav = pcm.reshape(1, -1).astype(np.float32)
            wl = np.array([wav.shape[1]], dtype=np.int64)
            feat, fl = mel_sess.run(None, {"waveforms": wav, "waveforms_lens": wl})
            sig = feat.astype(np.float32)
            length = fl.astype(np.int64)
            enc_out, _elen = enc_sess.run(None, {"audio_signal": sig, "length": length})
            ids = tdt_greedy(enc_out)
            return _decode_ids(ids, id_to_piece)

        buf = np.array([], dtype=np.float32)
        transcript = ""
        seg_i = 0

        def process_sliding(final: bool) -> None:
            nonlocal buf, transcript, seg_i
            while buf.size >= self.chunk_samples or (final and buf.size >= MIN_DECODE_SAMPLES):
                if buf.size < self.chunk_samples:
                    chunk = buf.copy()
                else:
                    chunk = buf[: self.chunk_samples].copy()
                t0 = time.perf_counter()
                text = run_decode_pcm(chunk)
                dt = time.perf_counter() - t0
                seg_i += 1
                log_line(
                    f"[transcriber] seg #{seg_i} samples={chunk.size} {dt:.2f}s text_len={len(text)}"
                )
                if text:
                    old = transcript
                    transcript = _merge_segment(transcript, text)
                    if transcript != old:
                        if transcript.startswith(old):
                            delta = transcript[len(old) :].lstrip()
                        else:
                            delta = transcript
                        if delta:
                            self._append_out(delta)
                if buf.size >= self.chunk_samples:
                    buf = buf[self.advance_samples :].copy()
                elif final:
                    buf = np.array([], dtype=np.float32)
                    break
            if final and buf.size > 0 and buf.size < MIN_DECODE_SAMPLES:
                buf = np.array([], dtype=np.float32)

        try:
            while True:
                try:
                    item = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    process_sliding(final=False)
                    continue
                if item is None:
                    self._phase("Final segments…")
                    process_sliding(final=True)
                    break
                f32 = _pcm16_to_f32_mono(item)
                if self.sample_rate_in != SR:
                    f32 = _resample_linear(f32, self.sample_rate_in, SR)
                if f32.size:
                    buf = np.concatenate([buf, f32])
                process_sliding(final=False)
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
