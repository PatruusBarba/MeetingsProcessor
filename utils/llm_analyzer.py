"""Background LLM analysis of meeting transcript for key points."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

_log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an AI assistant analyzing a live meeting transcript.
Your task: extract and maintain a concise list of KEY POINTS discussed so far.

Rules:
- Output ONLY a bullet list of key points (use "- " prefix).
- Each point should be one clear, concise sentence.
- Merge or update existing points when new context refines them.
- Remove points that are no longer relevant or were superseded.
- Keep the list ordered chronologically (oldest first).
- Do NOT add commentary, headers, or any text outside the bullet list.
- If the transcript is too short or unclear, output a single point summarizing what's available.
- Write in the SAME language as the transcript.
"""

USER_PROMPT_TEMPLATE = """\
=== CURRENT KEY POINTS ===
{key_points}

=== NEW TRANSCRIPT (since last analysis) ===
{new_transcript}

=== FULL TRANSCRIPT ===
{full_transcript}

Update the key points list based on the full transcript. Return ONLY the updated bullet list."""


class LlmAnalyzerThread(threading.Thread):
    """Background thread that periodically sends transcript to an LLM for key-point extraction."""

    def __init__(
        self,
        base_url: str,
        model: str,
        interval_sec: float,
        on_result: Callable[[str], None],
        on_error: Callable[[str], None],
        on_status: Callable[[str], None],
    ) -> None:
        super().__init__(daemon=True)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.interval_sec = max(5.0, interval_sec)
        self.on_result = on_result
        self.on_error = on_error
        self.on_status = on_status

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._transcript = ""
        self._last_analyzed_transcript = ""
        self._key_points = ""
        self._transcript_changed = threading.Event()

    def update_transcript(self, full_text: str) -> None:
        """Called from any thread when transcript changes."""
        with self._lock:
            self._transcript = full_text
        self._transcript_changed.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._transcript_changed.set()  # unblock wait

    def run(self) -> None:
        _log.info("[llm] analyzer started, url=%s model=%s interval=%.0fs",
                  self.base_url, self.model, self.interval_sec)
        self.on_status("LLM: connecting…")

        try:
            from openai import OpenAI
        except ImportError:
            self.on_error("openai package not installed")
            return

        client = OpenAI(base_url=self.base_url, api_key="not-needed")

        # Verify connection
        try:
            client.models.list()
            self.on_status("LLM: ready, waiting for transcript…")
        except Exception as e:
            self.on_error(f"LLM connection failed: {e}")
            return

        last_analysis_time = 0.0

        while not self._stop_event.is_set():
            # Wait for transcript changes or interval
            self._transcript_changed.wait(timeout=2.0)
            self._transcript_changed.clear()

            if self._stop_event.is_set():
                break

            with self._lock:
                current = self._transcript
                prev = self._last_analyzed_transcript

            # Skip if no new text or too soon
            if current == prev:
                continue
            elapsed = time.monotonic() - last_analysis_time
            if elapsed < self.interval_sec:
                continue

            new_text = current[len(prev):] if current.startswith(prev) else current
            if len(new_text.strip()) < 10:
                continue

            self.on_status("LLM: analyzing…")
            last_analysis_time = time.monotonic()

            try:
                user_msg = USER_PROMPT_TEMPLATE.format(
                    key_points=self._key_points or "(none yet)",
                    new_transcript=new_text.strip()[-3000:],
                    full_transcript=current.strip()[-6000:],
                )
                resp = client.chat.completions.create(
                    model=self.model or "",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                )
                result = resp.choices[0].message.content.strip()
                with self._lock:
                    self._key_points = result
                    self._last_analyzed_transcript = current
                self.on_result(result)
                self.on_status("LLM: idle")
            except Exception as e:
                _log.warning("[llm] analysis error: %s", e)
                self.on_error(f"LLM error: {e}")

        _log.info("[llm] analyzer stopped")
