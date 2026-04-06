"""UtteranceVAD align_start_with_preroll keeps audio before first speech frame."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from utils.speech_vad import UtteranceVAD


def test_align_preroll_keeps_samples_before_first_speech_frame() -> None:
    vad = UtteranceVAD(aggressiveness=0)
    pcm = np.arange(20_000, dtype=np.float32)
    first = 10_000
    preroll_samples = int(0.2 * 16_000)
    want_start = first - preroll_samples
    with patch.object(vad, "first_speech_frame_start", return_value=first):
        out = vad.align_start_with_preroll(pcm, preroll_sec=0.2)
    assert np.array_equal(out, pcm[want_start:])


def test_align_without_speech_returns_unchanged() -> None:
    vad = UtteranceVAD(aggressiveness=0)
    pcm = np.zeros(5_000, dtype=np.float32)
    with patch.object(vad, "first_speech_frame_start", return_value=None):
        out = vad.align_start_with_preroll(pcm, preroll_sec=0.35)
    assert np.array_equal(out, pcm)
