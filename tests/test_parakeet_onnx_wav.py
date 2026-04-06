"""Decode public speech WAVs with Parakeet ONNX when the model bundle is present."""

from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np
import pytest

from audio.parakeet_onnx_runtime import ParakeetOnnxDecoder
from utils.onnx_model_bundle import is_bundle_complete
from utils.constants import bundled_parakeet_onnx_dir

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LDC93S1 = FIXTURES / "ldc93s1.wav"


def _read_wav_mono_f32_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        pytest.skip(f"expected 16-bit wav, got width {sw}")
    a = np.frombuffer(raw, dtype=np.int16)
    if ch == 2:
        a = a.reshape(-1, 2).mean(axis=1).astype(np.int16)
    x = a.astype(np.float32) / 32768.0
    if sr != 16000:
        # simple linear resample
        ratio = 16000 / sr
        n_dst = max(1, int(len(x) * ratio))
        t_src = np.linspace(0.0, len(x) - 1, num=len(x), dtype=np.float64)
        t_dst = np.linspace(0.0, len(x) - 1, num=n_dst, dtype=np.float64)
        x = np.interp(t_dst, t_src, x.astype(np.float64)).astype(np.float32)
    return np.clip(x, -1.0, 1.0)


@pytest.fixture(scope="module")
def model_dir() -> str | None:
    d = bundled_parakeet_onnx_dir()
    if not is_bundle_complete(d):
        return None
    return d


@pytest.mark.skipif(not LDC93S1.is_file(), reason="fixture ldc93s1.wav missing (run tests from repo with fixtures)")
def test_ldc93s1_reference_transcript(model_dir: str | None) -> None:
    if model_dir is None:
        pytest.skip("Parakeet ONNX bundle not installed under models/")
    pcm = _read_wav_mono_f32_16k(LDC93S1)
    dec = ParakeetOnnxDecoder(model_dir, device="cpu")
    text = dec.decode_pcm_mono_16k_f32(pcm)
    # LibriSpeech LDC93S1 ground truth (common ASR smoke test)
    ref = "she had your dark suit in greasy wash water all year"
    norm = " ".join(text.lower().split())
    assert norm, f"empty transcript for {LDC93S1}"
    # Quantized model: allow partial match
    overlap = sum(1 for w in ref.split() if w in norm)
    assert overlap >= 6, f"expected most words from reference; got {text!r}"
