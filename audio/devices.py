"""Enumerate WASAPI input and output devices using PyAudioWPatch."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class AudioDevice:
    """Display entry for combobox; `device_index` is PortAudio index for opening streams."""

    device_index: int
    name: str
    default_sample_rate: int
    max_channels: int
    is_loopback: bool
    host_api: str

    def label(self) -> str:
        return f"{self.name} — {self.default_sample_rate} Hz"


def _get_pyaudio():
    if sys.platform != "win32":
        raise RuntimeError("This application requires Windows with WASAPI.")
    import pyaudiowpatch as pyaudio

    return pyaudio


def enumerate_devices(p_audio: Any) -> tuple[list[AudioDevice], list[AudioDevice]]:
    """
    Returns (input_devices_for_mic, output_devices_for_dropdown).
    Output list uses real output device indices; loopback index is resolved when recording.
    """
    pyaudio = _get_pyaudio()
    try:
        wasapi_info = p_audio.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        return [], []

    wasapi_index = wasapi_info["index"]
    inputs: list[AudioDevice] = []
    outputs: list[AudioDevice] = []

    for i in range(p_audio.get_device_count()):
        try:
            info = p_audio.get_device_info_by_index(i)
        except OSError:
            continue
        if info.get("hostApi") != wasapi_index:
            continue
        rate = int(info.get("defaultSampleRate") or 44100)
        name = str(info.get("name", f"Device {i}"))
        max_in = int(info.get("maxInputChannels", 0))
        max_out = int(info.get("maxOutputChannels", 0))
        is_lb = bool(info.get("isLoopbackDevice", False))

        if max_in > 0 and not is_lb:
            inputs.append(
                AudioDevice(
                    device_index=i,
                    name=name,
                    default_sample_rate=rate,
                    max_channels=max_in,
                    is_loopback=False,
                    host_api="WASAPI",
                )
            )
        if max_out > 0 and not is_lb:
            outputs.append(
                AudioDevice(
                    device_index=i,
                    name=name,
                    default_sample_rate=rate,
                    max_channels=max_out,
                    is_loopback=False,
                    host_api="WASAPI",
                )
            )

    return inputs, outputs


def resolve_loopback_device(p_audio: Any, output_device_index: int) -> dict[str, Any] | None:
    """Return device info dict for the loopback input corresponding to a WASAPI output index."""
    try:
        out_info = p_audio.get_device_info_by_index(output_device_index)
    except OSError:
        return None
    lb = p_audio.get_wasapi_loopback_analogue_by_dict(out_info)
    if lb is None:
        return None
    return lb


def open_shared_pyaudio():
    """Create one PyAudio instance for the app lifetime."""
    pyaudio = _get_pyaudio()
    return pyaudio.PyAudio()


def dev_stub_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Fake WASAPI entries for UI smoke tests (MEETING_RECORDER_DEV_UI=1)."""
    mic = AudioDevice(
        device_index=0,
        name="[DEV] Stub microphone",
        default_sample_rate=48000,
        max_channels=2,
        is_loopback=False,
        host_api="WASAPI",
    )
    spk = AudioDevice(
        device_index=1,
        name="[DEV] Stub speakers",
        default_sample_rate=48000,
        max_channels=2,
        is_loopback=False,
        host_api="WASAPI",
    )
    return [mic], [spk]
