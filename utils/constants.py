"""Application constants."""

import sys

APP_NAME = "Meeting Audio Recorder"
APP_VERSION = "1.0.0"

# Audio
AUDIO_FORMAT_BITS = 16
FRAMES_PER_BUFFER = 1024
MIX_CHUNK_SAMPLES = 1024
FALLBACK_SAMPLE_RATE = 44100
MP3_BITRATE_KBPS = 128

# Windows message for custom hotkey (WM_HOTKEY = 0x0312)
WM_HOTKEY = 0x0312

# Single-instance mutex name (global)
SINGLE_INSTANCE_MUTEX_NAME = "Local\\MeetingAudioRecorder_SingleInstance_v1"

# Hotkey (RegisterHotKey virtual-key code for 'R')
VK_R = 0x52


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "executable")


def app_dir() -> str:
    """Directory containing the executable or script (for settings, recordings default)."""
    import os

    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
