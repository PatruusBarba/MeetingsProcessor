"""Tests for cumulative transcript delta logic."""

import unittest


class TestDelta(unittest.TestCase):
    def test_empty_to_full(self) -> None:
        from audio.onnx_parakeet_stream_transcriber import _delta_from_full_decode

        self.assertEqual(_delta_from_full_decode("", "hello world"), "hello world")

    def test_prefix_growth(self) -> None:
        from audio.onnx_parakeet_stream_transcriber import _delta_from_full_decode

        self.assertEqual(_delta_from_full_decode("hello", "hello world"), "world")

    def test_correction(self) -> None:
        from audio.onnx_parakeet_stream_transcriber import _delta_from_full_decode

        d = _delta_from_full_decode("hel", "hello")
        self.assertTrue(d.startswith("lo") or "hello" in d)


if __name__ == "__main__":
    unittest.main()
