"""WASAPI microphone capture thread."""

from __future__ import annotations

import array
import queue
import threading
import time

import pyaudiowpatch as pyaudio

from audio.resample import downmix_int16, resample_mono_linear_int16


def _rms_level_percent(mono: bytes) -> int:
    if len(mono) < 2:
        return 0
    a = array.array("h")
    a.frombytes(mono)
    if not a:
        return 0
    rms = (sum(x * x for x in a) / len(a)) ** 0.5
    return min(100, int((rms / 32768.0) * 180))


class MicCaptureThread(threading.Thread):
    def __init__(
        self,
        p_audio: pyaudio.PyAudio,
        device_index: int,
        device_info: dict,
        out_queue: queue.Queue,
        target_sample_rate: int,
        level_pair: list,
        paused_event: threading.Event,
        stop_event: threading.Event,
        error_box: list,
    ) -> None:
        super().__init__(daemon=True)
        self.p_audio = p_audio
        self.device_index = device_index
        self.device_info = device_info
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
        channels = min(int(self.device_info.get("maxInputChannels", 1)), 2)
        if channels < 1:
            channels = 1
        native_rate = int(self.device_info.get("defaultSampleRate") or 44100)
        try:
            try:
                stream = self.p_audio.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=native_rate,
                    frames_per_buffer=1024,
                    input=True,
                    input_device_index=self.device_index,
                )
                with self._stream_lock:
                    self._stream = stream
            except OSError as e:
                self.error_box.append(("mic_open", str(e)))
                return

            while not self.stop_event.is_set():
                if self.paused_event.is_set():
                    time.sleep(0.02)
                    continue
                try:
                    data = self._stream.read(1024, exception_on_overflow=False)
                except OSError as e:
                    self.error_box.append(("mic_read", str(e)))
                    break
                mono = downmix_int16(data, channels)
                self.level_pair[0] = _rms_level_percent(mono)
                if native_rate != self.target_sample_rate:
                    mono = resample_mono_linear_int16(mono, native_rate, self.target_sample_rate)
                try:
                    self.out_queue.put(mono, timeout=2.0)
                except queue.Full:
                    self.error_box.append(("mic_queue", "Writer too slow"))
                    break
        finally:
            self.level_pair[0] = 0
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
