"""Unit tests for audio.resample (no PyAudio / Windows required)."""

import array
import unittest

from audio.resample import (
    StreamingLinearResamplerInt16,
    downmix_int16,
    resample_mono_linear_int16,
    stereo_to_mono_int16,
)


class TestStereoToMono(unittest.TestCase):
    def test_stereo_average(self) -> None:
        # L=1000, R=2000 -> 1500
        a = array.array("h", [1000, 2000])
        out = stereo_to_mono_int16(a.tobytes())
        b = array.array("h")
        b.frombytes(out)
        self.assertEqual(b.tolist(), [1500])


class TestDownmix(unittest.TestCase):
    def test_mono_passthrough(self) -> None:
        raw = array.array("h", [100, -200]).tobytes()
        self.assertEqual(downmix_int16(raw, 1), raw)

    def test_stereo(self) -> None:
        raw = array.array("h", [1000, 3000]).tobytes()
        out = downmix_int16(raw, 2)
        b = array.array("h")
        b.frombytes(out)
        self.assertEqual(b.tolist(), [2000])


class TestResampleLinear(unittest.TestCase):
    def test_same_rate(self) -> None:
        raw = array.array("h", [1000, 2000, 3000]).tobytes()
        self.assertEqual(resample_mono_linear_int16(raw, 48000, 48000), raw)

    def test_double_rate(self) -> None:
        raw = array.array("h", [0, 1000]).tobytes()
        out = resample_mono_linear_int16(raw, 24000, 48000)
        b = array.array("h")
        b.frombytes(out)
        self.assertGreater(len(b), 2)
        self.assertEqual(b[0], 0)
        self.assertEqual(b[-1], 1000)


class TestStreamingResampler(unittest.TestCase):
    def test_streaming_matches_one_shot_shape(self) -> None:
        samples = array.array("h", [0, 500, 1000, 1500, 2000, 2500])
        full = resample_mono_linear_int16(samples.tobytes(), 24000, 48000)
        rs = StreamingLinearResamplerInt16(24000, 48000)
        chunk_a = rs.process(array.array("h", samples[:3]).tobytes())
        chunk_b = rs.process(array.array("h", samples[3:]).tobytes())
        out = chunk_a + chunk_b + rs.flush()
        full_arr = array.array("h")
        full_arr.frombytes(full)
        out_arr = array.array("h")
        out_arr.frombytes(out)
        self.assertGreater(len(out_arr), 0)
        self.assertEqual(out_arr[0], full_arr[0])
        self.assertEqual(out_arr[-1], full_arr[-1])
        self.assertEqual(len(out_arr), len(full_arr))


if __name__ == "__main__":
    unittest.main()
