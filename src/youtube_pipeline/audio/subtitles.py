"""Subtitle cue building and SRT/VTT writers."""

from __future__ import annotations

from pathlib import Path

import srt

from youtube_pipeline.models import SubtitleCue, WordTimestamp
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


class SubtitleWriter:
    """Build timed subtitle cues and persist them as .srt / .vtt."""

    def __init__(self, *, max_chars_per_cue: int = 42, max_words_per_cue: int = 6) -> None:
        self.max_chars_per_cue = max_chars_per_cue
        self.max_words_per_cue = max_words_per_cue

    def build_cues(self, words: list[WordTimestamp]) -> list[SubtitleCue]:
        if not words:
            return []

        cues: list[SubtitleCue] = []
        bucket: list[WordTimestamp] = []
        cue_index = 1

        def flush() -> None:
            nonlocal cue_index, bucket
            if not bucket:
                return
            text = " ".join(w.word for w in bucket).strip()
            if text:
                cues.append(
                    SubtitleCue(
                        index=cue_index,
                        start=bucket[0].start,
                        end=max(bucket[-1].end, bucket[0].start + 0.35),
                        text=text,
                    )
                )
                cue_index += 1
            bucket = []

        for word in words:
            tentative = bucket + [word]
            text = " ".join(w.word for w in tentative)
            if bucket and (
                len(tentative) > self.max_words_per_cue or len(text) > self.max_chars_per_cue
            ):
                flush()
            bucket.append(word)

        flush()
        logger.debug("Built %d subtitle cues from %d words", len(cues), len(words))
        return cues

    def write_srt(self, cues: list[SubtitleCue], path: Path) -> Path:
        ensure_dir(path.parent)
        entries = [
            srt.Subtitle(
                index=cue.index,
                start=srt.timedelta(seconds=cue.start),
                end=srt.timedelta(seconds=cue.end),
                content=cue.text,
            )
            for cue in cues
        ]
        path.write_text(srt.compose(entries), encoding="utf-8")
        return path

    def write_vtt(self, cues: list[SubtitleCue], path: Path) -> Path:
        ensure_dir(path.parent)
        lines = ["WEBVTT", ""]
        for cue in cues:
            lines.append(f"{self._fmt_vtt(cue.start)} --> {self._fmt_vtt(cue.end)}")
            lines.append(cue.text)
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    @staticmethod
    def _fmt_vtt(seconds: float) -> str:
        millis = int(round(seconds * 1000))
        hours, rem = divmod(millis, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        secs, ms = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"
