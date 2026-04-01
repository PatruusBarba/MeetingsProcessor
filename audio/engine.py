"""Orchestrates mic + loopback capture, mixing, WAV write, MP3 encode."""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Callable

import pyaudiowpatch as pyaudio

from audio.devices import resolve_loopback_device
from audio.loopback import LoopbackCaptureThread
from audio.mic_capture import MicCaptureThread
from audio.mp3_encoder import wav_to_mp3_mono
from audio.wav_writer import MonoWavWriter
from utils.constants import FALLBACK_SAMPLE_RATE, MP3_BITRATE_KBPS


def _mix_sample(a: int, b: int) -> int:
    return max(-32768, min(32767, (a + b) // 2))


class WriterThread(threading.Thread):
    def __init__(
        self,
        mic_q: queue.Queue,
        loop_q: queue.Queue,
        wav_path: str,
        mp3_path: str,
        sample_rate: int,
        paused_event: threading.Event,
        mic_thread: threading.Thread,
        loop_thread: threading.Thread,
        on_disk_error: Callable[[str], None],
        on_convert_start: Callable[[], None],
        on_convert_done: Callable[[str], None],
        on_convert_error: Callable[[str], None],
    ) -> None:
        super().__init__(daemon=True)
        self.mic_q = mic_q
        self.loop_q = loop_q
        self.wav_path = wav_path
        self.mp3_path = mp3_path
        self.sample_rate = sample_rate
        self.paused_event = paused_event
        self.mic_thread = mic_thread
        self.loop_thread = loop_thread
        self.on_disk_error = on_disk_error
        self.on_convert_start = on_convert_start
        self.on_convert_done = on_convert_done
        self.on_convert_error = on_convert_error

    def run(self) -> None:
        writer = MonoWavWriter(self.wav_path, self.sample_rate)
        try:
            writer.open()
        except OSError as e:
            self.on_disk_error(str(e))
            return

        mic_buf = bytearray()
        loop_buf = bytearray()
        mic_done = False
        loop_done = False
        was_paused_flag = False

        def take_i16(buf: bytearray) -> int | None:
            if len(buf) < 2:
                return None
            v = int.from_bytes(buf[0:2], "little", signed=True)
            del buf[0:2]
            return v

        while not (mic_done and loop_done):
            paused = self.paused_event.is_set()

            if not mic_done:
                try:
                    item = self.mic_q.get(timeout=0.05)
                    if item is None:
                        mic_done = True
                    elif not paused:
                        mic_buf.extend(item)
                except queue.Empty:
                    pass

            if not loop_done:
                try:
                    item = self.loop_q.get(timeout=0.05)
                    if item is None:
                        loop_done = True
                    elif not paused:
                        loop_buf.extend(item)
                except queue.Empty:
                    pass

            if paused:
                time.sleep(0.02)
                was_paused_flag = True
                continue

            if was_paused_flag:
                mic_buf.clear()
                loop_buf.clear()
                was_paused_flag = False

            out_chunk = bytearray()
            while len(mic_buf) >= 2 and len(loop_buf) >= 2:
                a = take_i16(mic_buf)
                b = take_i16(loop_buf)
                if a is None or b is None:
                    break
                out_chunk.extend(_mix_sample(a, b).to_bytes(2, "little", signed=True))

            if out_chunk:
                try:
                    writer.write_pcm(bytes(out_chunk))
                except OSError as e:
                    self.on_disk_error(str(e))
                    writer.close()
                    return

        while True:
            if len(mic_buf) < 2 and len(loop_buf) < 2:
                break
            a = take_i16(mic_buf) if len(mic_buf) >= 2 else None
            b = take_i16(loop_buf) if len(loop_buf) >= 2 else None
            if a is None and b is None:
                break
            if a is None:
                a = 0
            if b is None:
                b = 0
            try:
                writer.write_pcm(_mix_sample(a, b).to_bytes(2, "little", signed=True))
            except OSError as e:
                self.on_disk_error(str(e))
                writer.close()
                return

        writer.close()

        if not os.path.isfile(self.wav_path):
            return

        self.on_convert_start()
        try:
            wav_to_mp3_mono(self.wav_path, self.mp3_path, MP3_BITRATE_KBPS)
            self.on_convert_done(self.mp3_path)
        except Exception as e:
            self.on_convert_error(str(e))


class RecordingEngine:
    def __init__(self, p_audio: pyaudio.PyAudio) -> None:
        self.p_audio = p_audio
        self._mic_q: queue.Queue | None = None
        self._loop_q: queue.Queue | None = None
        self._stop_event: threading.Event | None = None
        self._paused_event: threading.Event | None = None
        self._level_pair: list | None = None
        self._error_box: list | None = None
        self._mic_thread: MicCaptureThread | None = None
        self._loop_thread: LoopbackCaptureThread | None = None
        self._writer_thread: WriterThread | None = None

    def is_recording(self) -> bool:
        return self._stop_event is not None and not self._stop_event.is_set()

    def get_levels(self) -> tuple[int, int]:
        if self._level_pair is None:
            return 0, 0
        return int(self._level_pair[0]), int(self._level_pair[1])

    def get_errors(self) -> list[tuple[str, str]]:
        if not self._error_box:
            return []
        out = list(self._error_box)
        self._error_box.clear()
        return out

    def pause(self) -> None:
        if self._paused_event:
            self._paused_event.set()

    def resume(self) -> None:
        if self._paused_event:
            self._paused_event.clear()

    def is_paused(self) -> bool:
        return bool(self._paused_event and self._paused_event.is_set())

    def start(
        self,
        input_device_index: int,
        output_device_index: int,
        wav_path: str,
        mp3_path: str,
        on_disk_error: Callable[[str], None],
        on_convert_start: Callable[[], None],
        on_convert_done: Callable[[str], None],
        on_convert_error: Callable[[str], None],
    ) -> tuple[bool, str | None]:
        lb = resolve_loopback_device(self.p_audio, output_device_index)
        if lb is None:
            return False, "Could not resolve loopback device for the selected output."

        try:
            mic_info = self.p_audio.get_device_info_by_index(input_device_index)
        except OSError as e:
            return False, f"Microphone not available: {e}"

        mic_rate = int(mic_info.get("defaultSampleRate") or FALLBACK_SAMPLE_RATE)
        loop_rate = int(lb.get("defaultSampleRate") or FALLBACK_SAMPLE_RATE)
        target_rate = max(mic_rate, loop_rate)
        if target_rate <= 0:
            target_rate = FALLBACK_SAMPLE_RATE

        self._mic_q = queue.Queue(maxsize=256)
        self._loop_q = queue.Queue(maxsize=256)
        self._stop_event = threading.Event()
        self._paused_event = threading.Event()
        self._level_pair = [0, 0]
        self._error_box = []

        self._mic_thread = MicCaptureThread(
            self.p_audio,
            input_device_index,
            mic_info,
            self._mic_q,
            target_rate,
            self._level_pair,
            self._paused_event,
            self._stop_event,
            self._error_box,
        )
        self._loop_thread = LoopbackCaptureThread(
            self.p_audio,
            lb,
            self._loop_q,
            target_rate,
            self._level_pair,
            self._paused_event,
            self._stop_event,
            self._error_box,
        )

        self._writer_thread = WriterThread(
            self._mic_q,
            self._loop_q,
            wav_path,
            mp3_path,
            target_rate,
            self._paused_event,
            self._mic_thread,
            self._loop_thread,
            on_disk_error,
            on_convert_start,
            on_convert_done,
            on_convert_error,
        )

        self._writer_thread.start()
        self._mic_thread.start()
        self._loop_thread.start()
        return True, None

    def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()

        if self._mic_thread:
            self._mic_thread.join(timeout=5.0)
        if self._loop_thread:
            self._loop_thread.join(timeout=5.0)

        if self._writer_thread:
            self._writer_thread.join(timeout=600.0)

        self._mic_q = None
        self._loop_q = None
        self._stop_event = None
        self._paused_event = None
        self._level_pair = None
        self._error_box = None
        self._mic_thread = None
        self._loop_thread = None
        self._writer_thread = None
