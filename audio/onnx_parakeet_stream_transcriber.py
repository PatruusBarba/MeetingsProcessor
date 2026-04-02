"""
Live transcription with INT8 ONNX Parakeet TDT V3 (same layout as smcleod/parakeet-tdt-0.6b-v3-int8
and local folders: nemo128.onnx, encoder-model.int8.onnx, decoder_joint-model.int8.onnx, vocab.txt).

No NeMo / PyTorch. ONNX Runtime + TDT greedy decode (same logic as nano-parakeet).
Encoder ONNX is full-sequence: we re-run mel+encoder on growing 16 kHz PCM, throttled by
``min_interval_sec`` so the transcript updates smoothly without re-decoding every tiny chunk.
"""

from __future__ import annotations

import array
import os
import queue
import threading
import time
from typing import Callable

import numpy as np

BLANK_ID = 8192
DURATIONS = [0, 1, 2, 3, 4]
N_DUR = len(DURATIONS)


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
        min_interval_sec: float,
        on_model_loading: Callable[[], None] | None,
        on_error: Callable[[str], None] | None,
    ) -> None:
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.sample_rate_in = sample_rate_in
        self.text_queue = text_queue
        self.model_dir = os.path.abspath(model_dir)
        self.device = device
        self.min_interval_sec = max(0.12, float(min_interval_sec))
        self.on_model_loading = on_model_loading
        self.on_error = on_error

    def run(self) -> None:
        try:
            import onnxruntime as ort
        except ImportError:
            if self.on_error:
                self.on_error(
                    "Install ONNX Runtime:\n  pip install onnxruntime\n"
                    "For NVIDIA GPU: pip install onnxruntime-gpu"
                )
            self.text_queue.put(None)
            return

        mel_path = os.path.join(self.model_dir, "nemo128.onnx")
        enc_path = os.path.join(self.model_dir, "encoder-model.int8.onnx")
        dec_path = os.path.join(self.model_dir, "decoder_joint-model.int8.onnx")
        vocab_path = os.path.join(self.model_dir, "vocab.txt")
        for p in (mel_path, enc_path, dec_path, vocab_path):
            if not os.path.isfile(p):
                if self.on_error:
                    self.on_error(
                        f"Missing file in model folder:\n{p}\n\n"
                        "Need: nemo128.onnx, encoder-model.int8.onnx, "
                        "decoder_joint-model.int8.onnx, vocab.txt"
                    )
                self.text_queue.put(None)
                return

        if self.on_model_loading:
            self.on_model_loading()

        try:
            id_to_piece = _load_vocab_txt(vocab_path)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Failed to read vocab.txt: {e}")
            self.text_queue.put(None)
            return

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = _ort_providers(self.device)
        try:
            mel_sess = ort.InferenceSession(mel_path, so, providers=providers)
            enc_sess = ort.InferenceSession(enc_path, so, providers=providers)
            dec_sess = ort.InferenceSession(dec_path, so, providers=providers)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Failed to load ONNX: {e}\nProviders tried: {providers}")
            self.text_queue.put(None)
            return

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

        def run_decode(pcm_16k: np.ndarray) -> str:
            if pcm_16k.size < 800:
                return ""
            wav = pcm_16k.reshape(1, -1).astype(np.float32)
            wl = np.array([wav.shape[1]], dtype=np.int64)
            feat, fl = mel_sess.run(None, {"waveforms": wav, "waveforms_lens": wl})
            sig = feat.astype(np.float32)
            length = fl.astype(np.int64)
            enc_out, _elen = enc_sess.run(None, {"audio_signal": sig, "length": length})
            ids = tdt_greedy(enc_out)
            return _decode_ids(ids, id_to_piece)

        pcm_16k_buf = np.array([], dtype=np.float32)
        last_decode = 0.0
        last_text = ""

        def maybe_decode(force: bool) -> None:
            nonlocal last_decode, last_text
            now = time.monotonic()
            if pcm_16k_buf.size < 1600 and not force:
                return
            if not force and (now - last_decode) < self.min_interval_sec:
                return
            text = run_decode(pcm_16k_buf)
            last_decode = now
            if text != last_text:
                last_text = text
                self.text_queue.put(text)

        try:
            while True:
                try:
                    item = self.audio_queue.get(timeout=0.15)
                except queue.Empty:
                    maybe_decode(force=False)
                    continue
                if item is None:
                    maybe_decode(force=True)
                    break
                f32 = _pcm16_to_f32_mono(item)
                if self.sample_rate_in != 16000:
                    f32 = _resample_linear(f32, self.sample_rate_in, 16000)
                if f32.size:
                    pcm_16k_buf = np.concatenate([pcm_16k_buf, f32])
                maybe_decode(force=False)
        except Exception as e:
            if self.on_error:
                self.on_error(f"ONNX transcription error: {e}")
        finally:
            self.text_queue.put(None)
