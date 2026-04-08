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
