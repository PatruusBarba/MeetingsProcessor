"""Background LLM analysis of meeting transcript for key points."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

_log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an AI assistant analyzing a live meeting transcript in real time.
Your ONLY job: maintain a SHORT list of high-level KEY TAKEAWAYS — the important decisions, facts, conclusions, action items, or topics being discussed.

STRICT RULES:
- Output ONLY a bullet list (use "• " prefix). NO headers, NO commentary, NO numbering.
- MAX 7-10 bullet points. Fewer is better. Merge related ideas into one point.
- Each bullet = one concise phrase or short sentence (max ~15 words).
- DO NOT paraphrase or summarize every sentence. Extract only what MATTERS.
- Focus on: decisions made, action items, important facts/numbers, key opinions, topics discussed.
- IGNORE filler, repetitions, greetings, small talk.
- Keep existing points WORD-FOR-WORD unless they are obsolete or need merging.
- DO remove points that are redundant, superseded, or no longer relevant.
- DO merge two related points into one when it makes sense.
- Only ADD new points when there is genuinely new information.
- Chronological order (oldest topic first).
- Write in the SAME language as the transcript.
"""

USER_PROMPT_TEMPLATE = """\
=== CURRENT KEY POINTS ===
{key_points}

=== LATEST TRANSCRIPT CHUNK ===
{new_transcript}

=== FULL TRANSCRIPT (for context) ===
{full_transcript}

Return the updated bullet list. Keep unchanged points word-for-word. Remove redundant or obsolete points. Add new ones only for genuinely new info."""


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
        on_chunk: Callable[[str], None] | None = None,
        on_stream_start: Callable[[], None] | None = None,
        on_stream_done: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.interval_sec = max(5.0, interval_sec)
        self.on_result = on_result
        self.on_error = on_error
        self.on_status = on_status
        self.on_chunk = on_chunk
        self.on_stream_start = on_stream_start
        self.on_stream_done = on_stream_done

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
                if self.on_stream_start:
                    self.on_stream_start()
                stream = client.chat.completions.create(
                    model=self.model or "",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.2,
                    max_tokens=512,
                    stream=True,
                )
                full_result = []
                for chunk in stream:
                    if self._stop_event.is_set():
                        break
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        full_result.append(delta)
                        if self.on_chunk:
                            self.on_chunk(delta)
                result = "".join(full_result).strip()
                with self._lock:
                    self._key_points = result
                    self._last_analyzed_transcript = current
                if self.on_stream_done:
                    self.on_stream_done(result)
                self.on_result(result)
                self.on_status("LLM: idle")
            except Exception as e:
                _log.warning("[llm] analysis error: %s", e)
                self.on_error(f"LLM error: {e}")

        _log.info("[llm] analyzer stopped")
