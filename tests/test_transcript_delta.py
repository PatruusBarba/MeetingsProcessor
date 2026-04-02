"""Tests for sliding-window transcript merge."""

import unittest


class TestMerge(unittest.TestCase):
    def test_first(self) -> None:
        from audio.onnx_parakeet_stream_transcriber import _merge_segment

        self.assertEqual(_merge_segment("", "hello"), "hello")

    def test_append(self) -> None:
        from audio.onnx_parakeet_stream_transcriber import _merge_segment

        self.assertEqual(_merge_segment("hello", "world"), "hello world")

    def test_overlap_dup(self) -> None:
        from audio.onnx_parakeet_stream_transcriber import _merge_segment

        m = _merge_segment("hello wor", "world today")
        self.assertIn("today", m)


if __name__ == "__main__":
    unittest.main()
