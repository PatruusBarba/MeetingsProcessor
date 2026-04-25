"""Linear resampling for int16 PCM (mono)."""

from __future__ import annotations

import array


def stereo_to_mono_int16(data: bytes) -> bytes:
    """Average L/R for interleaved stereo int16."""
    if len(data) < 4:
        return b""
    n = len(data) // 4
    out = array.array("h", [0]) * n
    a = array.array("h")
    a.frombytes(data[: n * 4])
    for i in range(n):
        l = a[i * 2]
        r = a[i * 2 + 1]
        out[i] = (l + r) // 2
    return out.tobytes()


def downmix_int16(data: bytes, channels: int) -> bytes:
    if channels <= 0:
        return b""
    if channels == 1:
        return data
    if channels == 2:
        return stereo_to_mono_int16(data)
    # N channels: average groups
    sample_size = 2 * channels
    n = len(data) // sample_size
    if n == 0:
        return b""
    a = array.array("h")
    a.frombytes(data[: n * sample_size])
    out = array.array("h", [0]) * n
    for i in range(n):
        base = i * channels
        s = 0
        for c in range(channels):
            s += a[base + c]
        out[i] = s // channels
    return out.tobytes()


def resample_mono_linear_int16(mono_pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    if src_rate == dst_rate or not mono_pcm:
        return mono_pcm
    inp = array.array("h")
    inp.frombytes(mono_pcm)
    if len(inp) < 2:
        return mono_pcm
    ratio = dst_rate / src_rate
    out_len = max(1, int(len(inp) * ratio))
    out = array.array("h", [0]) * out_len
    for j in range(out_len):
        src_pos = j / ratio
        i0 = int(src_pos)
        i1 = min(i0 + 1, len(inp) - 1)
        frac = src_pos - i0
        v0 = inp[i0]
        v1 = inp[i1]
        out[j] = int(v0 + (v1 - v0) * frac)
    return out.tobytes()


class StreamingLinearResamplerInt16:
    """Streaming linear mono int16 resampler that preserves fractional position across chunks."""

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = max(1, int(src_rate))
        self.dst_rate = max(1, int(dst_rate))
        self._out_ratio = self.dst_rate / self.src_rate
        self._buffer = array.array("h")
        self._buffer_base = 0
        self._total_in = 0
        self._total_out = 0

    def _compact_buffer(self) -> None:
        if len(self._buffer) < 2:
            return
        next_src_pos = self._total_out / self._out_ratio
        keep_from_global = max(0, int(next_src_pos) - 1)
        drop = keep_from_global - self._buffer_base
        if drop > 0:
            del self._buffer[:drop]
            self._buffer_base += drop

    def _emit(self, target_out: int, *, allow_last_sample: bool) -> bytes:
        if not self._buffer:
            return b""
        out = array.array("h")
        while self._total_out < target_out:
            src_pos = self._total_out / self._out_ratio
            if not allow_last_sample and src_pos >= self._total_in - 1:
                break
            local_pos = src_pos - self._buffer_base
            if local_pos < 0:
                local_pos = 0.0
            i0 = int(local_pos)
            if i0 >= len(self._buffer):
                break
            i1 = min(i0 + 1, len(self._buffer) - 1)
            frac = 0.0 if i0 == i1 else local_pos - i0
            v0 = self._buffer[i0]
            v1 = self._buffer[i1]
            out.append(int(v0 + (v1 - v0) * frac))
            self._total_out += 1
        self._compact_buffer()
        return out.tobytes()

    def process(self, mono_pcm: bytes) -> bytes:
        if self.src_rate == self.dst_rate or not mono_pcm:
            return mono_pcm
        inp = array.array("h")
        inp.frombytes(mono_pcm)
        if not inp:
            return b""
        self._buffer.extend(inp)
        self._total_in += len(inp)
        target_out = int(self._total_in * self._out_ratio)
        return self._emit(target_out, allow_last_sample=False)

    def flush(self) -> bytes:
        if self.src_rate == self.dst_rate:
            return b""
        target_out = int(self._total_in * self._out_ratio)
        out = self._emit(target_out, allow_last_sample=True)
        self._buffer = array.array("h")
        self._buffer_base = self._total_in
        return out
