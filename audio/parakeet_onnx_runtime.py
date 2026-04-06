"""Parakeet TDT INT8 ONNX decode path (mel + encoder + greedy decoder) for reuse in tests and live thread."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import onnxruntime as ort

BLANK_ID = 8192
DURATIONS = [0, 1, 2, 3, 4]
N_DUR = len(DURATIONS)
MIN_WAVEFORM_PAD_SAMPLES = 16_000


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


class ParakeetOnnxDecoder:
    """16 kHz mono float32 PCM [-1,1] in, text out."""

    def __init__(self, model_dir: str, device: str = "cpu") -> None:
        import onnxruntime as ort

        self.model_dir = os.path.abspath(model_dir)
        mel_path = os.path.join(self.model_dir, "nemo128.onnx")
        enc_path = os.path.join(self.model_dir, "encoder-model.int8.onnx")
        dec_path = os.path.join(self.model_dir, "decoder_joint-model.int8.onnx")
        vocab_path = os.path.join(self.model_dir, "vocab.txt")
        for p in (mel_path, enc_path, dec_path, vocab_path):
            if not os.path.isfile(p):
                raise FileNotFoundError(p)
        self._id_to_piece = _load_vocab_txt(vocab_path)
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = _ort_providers(device)
        self._mel = ort.InferenceSession(mel_path, so, providers=providers)
        self._enc = ort.InferenceSession(enc_path, so, providers=providers)
        self._dec = ort.InferenceSession(dec_path, so, providers=providers)

    def decode_pcm_mono_16k_f32(self, pcm: np.ndarray) -> str:
        pcm = np.ascontiguousarray(pcm, dtype=np.float32).reshape(-1)
        n = int(pcm.size)
        if n < 400:
            return ""
        if n < MIN_WAVEFORM_PAD_SAMPLES:
            pcm = np.concatenate([pcm, np.zeros(MIN_WAVEFORM_PAD_SAMPLES - n, dtype=np.float32)])
        wav = pcm.reshape(1, -1).astype(np.float32)
        wl = np.array([wav.shape[1]], dtype=np.int64)
        feat, fl = self._mel.run(None, {"waveforms": wav, "waveforms_lens": wl})
        sig = feat.astype(np.float32)
        length = fl.astype(np.int64)
        enc_out, _elen = self._enc.run(None, {"audio_signal": sig, "length": length})
        ids = self._tdt_greedy(enc_out)
        return _decode_ids(ids, self._id_to_piece)

    def _tdt_greedy(self, enc_full: np.ndarray) -> list[int]:
        dec_sess = self._dec
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
