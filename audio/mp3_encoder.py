"""WAV to MP3 using lameenc (mono 128 kbps)."""

from __future__ import annotations

import os
import wave

import lameenc


def wav_to_mp3_mono(
    wav_path: str,
    mp3_path: str,
    bitrate_kbps: int = 128,
) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(mp3_path)) or ".", exist_ok=True)
    with wave.open(wav_path, "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        rate = wf.getframerate()
        if sample_width != 2:
            raise ValueError("Expected 16-bit WAV")
        enc = lameenc.Encoder()
        enc.set_bit_rate(bitrate_kbps)
        enc.set_in_sample_rate(rate)
        enc.set_channels(1)
        enc.set_quality(2)
        mp3_data = bytearray()
        chunk_frames = 1152
        while True:
            raw = wf.readframes(chunk_frames)
            if not raw:
                break
            if channels == 2:
                import array

                a = array.array("h")
                a.frombytes(raw)
                mono = array.array("h", [(a[i] + a[i + 1]) // 2 for i in range(0, len(a), 2)])
                raw = mono.tobytes()
            elif channels != 1:
                raise ValueError("Unsupported channel count for MP3 export")
            mp3_data.extend(enc.encode(raw))
        mp3_data.extend(enc.flush())
    with open(mp3_path, "wb") as out:
        out.write(mp3_data)
    os.remove(wav_path)
