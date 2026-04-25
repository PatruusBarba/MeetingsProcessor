"""WASAPI loopback capture thread."""

from __future__ import annotations

import array
import queue
import threading
import time

import pyaudiowpatch as pyaudio

from audio.resample import StreamingLinearResamplerInt16, downmix_int16


def _rms_level_percent(mono: bytes) -> int:
    if len(mono) < 2:
        return 0
    a = array.array("h")
    a.frombytes(mono)
    if not a:
        return 0
    rms = (sum(x * x for x in a) / len(a)) ** 0.5
    return min(100, int((rms / 32768.0) * 180))


class LoopbackCaptureThread(threading.Thread):
    def __init__(
        self,
        p_audio: pyaudio.PyAudio,
        loopback_info: dict,
        out_queue: queue.Queue,
        target_sample_rate: int,
        level_pair: list,
        paused_event: threading.Event,
        stop_event: threading.Event,
        error_box: list,
    ) -> None:
        super().__init__(daemon=True)
        self.p_audio = p_audio
        self.loopback_info = loopback_info
        self.out_queue = out_queue
        self.target_sample_rate = target_sample_rate
        self.level_pair = level_pair
        self.paused_event = paused_event
        self.stop_event = stop_event
        self.error_box = error_box
        self._stream = None
        self._stream_lock = threading.Lock()

    def halt_stream(self) -> None:
        """Unblock a stuck read(); safe to call from another thread."""
        with self._stream_lock:
            s = self._stream
        if s is None:
            return
        try:
            s.stop_stream()
        except OSError:
            pass

    def run(self) -> None:
        lb = self.loopback_info
        device_index = int(lb["index"])
        channels = min(int(lb.get("maxInputChannels", 2)), 2)
        if channels < 1:
            channels = 1
        native_rate = int(lb.get("defaultSampleRate") or 44100)
        resampler = None
        if native_rate != self.target_sample_rate:
            resampler = StreamingLinearResamplerInt16(native_rate, self.target_sample_rate)
        try:
            try:
                stream = self.p_audio.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=native_rate,
                    frames_per_buffer=1024,
                    input=True,
                    input_device_index=device_index,
                )
                with self._stream_lock:
                    self._stream = stream
            except OSError as e:
                self.error_box.append(("loopback_open", str(e)))
                return

            while not self.stop_event.is_set():
                if self.paused_event.is_set():
                    time.sleep(0.02)
                    continue
                try:
                    data = self._stream.read(1024, exception_on_overflow=False)
                except OSError as e:
                    self.error_box.append(("loopback_read", str(e)))
                    break
                mono = downmix_int16(data, channels)
                self.level_pair[1] = _rms_level_percent(mono)
                if resampler is not None:
                    mono = resampler.process(mono)
                try:
                    self.out_queue.put(mono, timeout=2.0)
                except queue.Full:
                    self.error_box.append(("loopback_queue", "Writer too slow"))
                    break
        finally:
            if resampler is not None:
                try:
                    tail = resampler.flush()
                    if tail:
                        self.out_queue.put(tail, timeout=2.0)
                except queue.Full:
                    self.error_box.append(("loopback_queue", "Writer too slow"))
            self.level_pair[1] = 0
            with self._stream_lock:
                s = self._stream
                self._stream = None
            if s:
                try:
                    s.stop_stream()
                    s.close()
                except OSError:
                    pass
            try:
                self.out_queue.put(None, timeout=5.0)
            except queue.Full:
                pass
