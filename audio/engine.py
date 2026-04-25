"""Orchestrates mic + loopback capture, mixing, WAV write, MP3 encode."""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Callable

_log = logging.getLogger(__name__)

import numpy as np
import pyaudiowpatch as pyaudio

from audio.devices import resolve_loopback_device
from audio.onnx_parakeet_stream_transcriber import OnnxParakeetLiveTranscriberThread
from audio.loopback import LoopbackCaptureThread
from audio.mic_capture import MicCaptureThread
from audio.mp3_encoder import wav_to_mp3_mono
from audio.wav_writer import MonoWavWriter
from utils.constants import FALLBACK_SAMPLE_RATE, MP3_BITRATE_KBPS
from utils.onnx_model_bundle import is_bundle_complete, resolve_transcription_model_dir


def _mix_sample(a: int, b: int) -> int:
    return max(-32768, min(32767, (a + b) // 2))


def _mix_pcm16_chunks(a_pcm: bytes | memoryview, b_pcm: bytes | memoryview) -> bytes:
    if not a_pcm or not b_pcm:
        return b""
    a = np.frombuffer(a_pcm, dtype=np.int16).astype(np.int32)
    b = np.frombuffer(b_pcm, dtype=np.int16).astype(np.int32)
    mixed = ((a + b) // 2).astype(np.int16, copy=False)
    return mixed.tobytes()


def _mix_pcm16_chunks_for_transcriber(a_pcm: bytes | memoryview, b_pcm: bytes | memoryview) -> bytes:
    """Mix for STT while preserving amplitude when only one side is effectively active."""
    if not a_pcm and not b_pcm:
        return b""
    if not a_pcm:
        return bytes(b_pcm)
    if not b_pcm:
        return bytes(a_pcm)
    a = np.frombuffer(a_pcm, dtype=np.int16).astype(np.int32)
    b = np.frombuffer(b_pcm, dtype=np.int16).astype(np.int32)
    # If one side is effectively silent, keep the active side unchanged so VAD/STT
    # do not see speech attenuated by ~50%.
    silence_rms = 220.0
    rms_a = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
    rms_b = float(np.sqrt(np.mean(b * b))) if b.size else 0.0
    if rms_a <= silence_rms and rms_b > silence_rms:
        mixed = b
    elif rms_b <= silence_rms and rms_a > silence_rms:
        mixed = a
    else:
        mixed = np.clip(a + b, -32768, 32767)
    return mixed.astype(np.int16, copy=False).tobytes()


def _mix_pcm16_with_zero(pcm: bytes | memoryview) -> bytes:
    if not pcm:
        return b""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.int32)
    return (samples // 2).astype(np.int16, copy=False).tobytes()


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
        on_convert_progress: Callable[[float], None] | None = None,
        transcriber_audio_q: queue.Queue | None = None,
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
        self.on_convert_progress = on_convert_progress
        self.transcriber_audio_q = transcriber_audio_q
        self._transcriber_drop_count = 0
        self._last_transcriber_backlog_log = 0.0

    def _feed_transcriber(self, mono_pcm: bytes) -> None:
        if not self.transcriber_audio_q or not mono_pcm:
            return
        q = self.transcriber_audio_q
        now = time.monotonic()
        if q.maxsize and q.qsize() >= max(1, int(q.maxsize * 0.75)):
            if now - self._last_transcriber_backlog_log >= 5.0:
                self._last_transcriber_backlog_log = now
                _log.warning(
                    "Transcriber backlog high: %d/%d chunks queued",
                    q.qsize(),
                    q.maxsize,
                )
        try:
            q.put_nowait(mono_pcm)
        except queue.Full:
            self._transcriber_drop_count += 1
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(mono_pcm)
            except queue.Full:
                pass
            if now - self._last_transcriber_backlog_log >= 2.0:
                self._last_transcriber_backlog_log = now
                _log.warning(
                    "Transcriber backlog full; dropped %d chunks to stay realtime",
                    self._transcriber_drop_count,
                )

    def _end_transcriber_feed(self) -> None:
        if not self.transcriber_audio_q:
            return
        q = self.transcriber_audio_q
        for _ in range(200):
            try:
                q.put_nowait(None)
                return
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    time.sleep(0.01)
        try:
            q.put(None, timeout=2.0)
        except queue.Full:
            pass

    def run(self) -> None:
        writer = MonoWavWriter(self.wav_path, self.sample_rate)
        try:
            writer.open()
        except OSError as e:
            self.on_disk_error(str(e))
            self._end_transcriber_feed()
            return

        mic_buf = bytearray()
        loop_buf = bytearray()
        mic_pos = 0
        loop_pos = 0
        mic_done = False
        loop_done = False
        was_paused_flag = False
        max_skew_bytes = max(2, int(self.sample_rate * 2 * 0.35))
        solo_emit_threshold = max(4096, int(self.sample_rate * 2 * 0.08)) & ~1
        chunk_limit_bytes = max(4096, int(self.sample_rate * 2 * 0.25)) & ~1
        compact_threshold = 128 * 1024
        last_skew_log = 0.0

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
                mic_pos = 0
                loop_pos = 0
                was_paused_flag = False

            mic_avail = max(0, len(mic_buf) - mic_pos)
            loop_avail = max(0, len(loop_buf) - loop_pos)
            diff = mic_avail - loop_avail
            mix_bytes = min(mic_avail, loop_avail, chunk_limit_bytes) & ~1
            if mix_bytes:
                mic_chunk = bytes(mic_buf[mic_pos : mic_pos + mix_bytes])
                loop_chunk = bytes(loop_buf[loop_pos : loop_pos + mix_bytes])
                raw = _mix_pcm16_chunks(
                    mic_chunk,
                    loop_chunk,
                )
                transcriber_raw = _mix_pcm16_chunks_for_transcriber(mic_chunk, loop_chunk)
                mic_pos += mix_bytes
                loop_pos += mix_bytes
                try:
                    writer.write_pcm(raw)
                    self._feed_transcriber(transcriber_raw)
                except OSError as e:
                    self.on_disk_error(str(e))
                    writer.close()
                    self._end_transcriber_feed()
                    return
            else:
                solo_bytes = 0
                mic_solo = False
                if mic_avail >= solo_emit_threshold and loop_avail == 0:
                    solo_bytes = min(mic_avail, chunk_limit_bytes) & ~1
                    mic_solo = True
                elif loop_avail >= solo_emit_threshold and mic_avail == 0:
                    solo_bytes = min(loop_avail, chunk_limit_bytes) & ~1
                elif diff > max_skew_bytes and mic_avail >= solo_emit_threshold and loop_avail < solo_emit_threshold:
                    solo_bytes = min(max_skew_bytes, chunk_limit_bytes, mic_avail) & ~1
                    mic_solo = True
                elif diff < -max_skew_bytes and loop_avail >= solo_emit_threshold and mic_avail < solo_emit_threshold:
                    solo_bytes = min(max_skew_bytes, chunk_limit_bytes, loop_avail) & ~1
                if solo_bytes:
                    if mic_solo:
                        mic_chunk = bytes(mic_buf[mic_pos : mic_pos + solo_bytes])
                        raw = _mix_pcm16_with_zero(mic_chunk)
                        transcriber_raw = mic_chunk
                        mic_pos += solo_bytes
                    else:
                        loop_chunk = bytes(loop_buf[loop_pos : loop_pos + solo_bytes])
                        raw = _mix_pcm16_with_zero(loop_chunk)
                        transcriber_raw = loop_chunk
                        loop_pos += solo_bytes
                    now = time.monotonic()
                    if now - last_skew_log >= 5.0:
                        last_skew_log = now
                        _log.warning(
                            "Writer emitted solo audio chunk (mic=%d loop=%d solo=%d source=%s)",
                            mic_avail,
                            loop_avail,
                            solo_bytes,
                            "mic" if mic_solo else "loop",
                        )
                    try:
                        writer.write_pcm(raw)
                        self._feed_transcriber(transcriber_raw)
                    except OSError as e:
                        self.on_disk_error(str(e))
                        writer.close()
                        self._end_transcriber_feed()
                        return

            if mic_pos >= compact_threshold and mic_pos >= len(mic_buf) // 2:
                del mic_buf[:mic_pos]
                mic_pos = 0
            if loop_pos >= compact_threshold and loop_pos >= len(loop_buf) // 2:
                del loop_buf[:loop_pos]
                loop_pos = 0

        while True:
            mic_avail = (len(mic_buf) - mic_pos) & ~1
            loop_avail = (len(loop_buf) - loop_pos) & ~1
            if mic_avail < 2 and loop_avail < 2:
                break
            if mic_avail and loop_avail:
                chunk_bytes = min(mic_avail, loop_avail)
                mic_chunk = bytes(mic_buf[mic_pos : mic_pos + chunk_bytes])
                loop_chunk = bytes(loop_buf[loop_pos : loop_pos + chunk_bytes])
                raw = _mix_pcm16_chunks(
                    mic_chunk,
                    loop_chunk,
                )
                transcriber_raw = _mix_pcm16_chunks_for_transcriber(mic_chunk, loop_chunk)
                mic_pos += chunk_bytes
                loop_pos += chunk_bytes
            elif mic_avail:
                mic_chunk = bytes(mic_buf[mic_pos : mic_pos + mic_avail])
                raw = _mix_pcm16_with_zero(mic_chunk)
                transcriber_raw = mic_chunk
                mic_pos += mic_avail
            else:
                loop_chunk = bytes(loop_buf[loop_pos : loop_pos + loop_avail])
                raw = _mix_pcm16_with_zero(loop_chunk)
                transcriber_raw = loop_chunk
                loop_pos += loop_avail
            try:
                writer.write_pcm(raw)
                self._feed_transcriber(transcriber_raw)
            except OSError as e:
                self.on_disk_error(str(e))
                writer.close()
                self._end_transcriber_feed()
                return

        writer.close()
        self._end_transcriber_feed()

        if not os.path.isfile(self.wav_path):
            return

        self.on_convert_start()
        try:
            wav_to_mp3_mono(self.wav_path, self.mp3_path, MP3_BITRATE_KBPS,
                            on_progress=self.on_convert_progress)
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
        self._transcriber_thread: LiveTranscriberThread | None = None
        self._transcriber_audio_q: queue.Queue | None = None

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
        on_convert_progress: Callable[[float], None] | None = None,
        *,
        transcription_enabled: bool = False,
        transcription_text_queue: queue.Queue | None = None,
        transcription_model_dir: str | None = "",
        transcription_device: str = "cpu",
        transcription_min_utterance_sec: float = 10.0,
        transcription_max_utterance_sec: float = 60.0,
        transcription_end_silence_sec: float = 1.2,
        transcription_vad_aggressiveness: int = 1,
        transcription_vad_preroll_sec: float = 0.55,
        on_transcription_model_loading: Callable[[], None] | None = None,
        on_transcription_error: Callable[[str], None] | None = None,
        on_transcription_status: Callable[[str], None] | None = None,
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

        trans_q: queue.Queue | None = None
        if transcription_enabled and transcription_text_queue is not None:
            mdir = resolve_transcription_model_dir(transcription_model_dir)
            if not is_bundle_complete(mdir):
                return False, "Transcription: download the ONNX model in Settings first."
            # Bounded backlog: enough headroom for ONNX startup/slowdown without allowing runaway memory growth.
            trans_q = queue.Queue(maxsize=4096)
            self._transcriber_audio_q = trans_q
            self._transcriber_thread = OnnxParakeetLiveTranscriberThread(
                trans_q,
                target_rate,
                transcription_text_queue,
                mdir,
                transcription_device,
                transcription_min_utterance_sec,
                transcription_max_utterance_sec,
                transcription_end_silence_sec,
                transcription_vad_aggressiveness,
                transcription_vad_preroll_sec,
                on_transcription_model_loading,
                on_transcription_error,
                on_transcription_status,
            )
            self._transcriber_thread.start()

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
            on_convert_progress=on_convert_progress,
            transcriber_audio_q=trans_q,
        )

        self._writer_thread.start()
        self._mic_thread.start()
        self._loop_thread.start()
        return True, None

    def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()

        # Unblock PortAudio read() so capture threads can exit and send queue sentinels.
        if self._mic_thread and hasattr(self._mic_thread, "halt_stream"):
            self._mic_thread.halt_stream()
        if self._loop_thread and hasattr(self._loop_thread, "halt_stream"):
            self._loop_thread.halt_stream()

        if self._mic_thread:
            self._mic_thread.join(timeout=15.0)
        if self._loop_thread:
            self._loop_thread.join(timeout=15.0)

        if self._writer_thread:
            self._writer_thread.join(timeout=120.0)
            if self._writer_thread.is_alive():
                _log.warning("Writer thread did not finish within 120s timeout")

        if self._transcriber_thread:
            self._transcriber_thread.join(timeout=120.0)
            if self._transcriber_thread.is_alive():
                _log.warning(
                    "Transcriber thread did not finish within 120s — "
                    "daemon thread will be abandoned on exit"
                )

        self._mic_q = None
        self._loop_q = None
        self._stop_event = None
        self._paused_event = None
        self._level_pair = None
        self._error_box = None
        self._mic_thread = None
        self._loop_thread = None
        self._writer_thread = None
        self._transcriber_thread = None
        self._transcriber_audio_q = None
