from __future__ import annotations

from pathlib import Path

from youtube_pipeline.audio.subtitles import SubtitleWriter
from youtube_pipeline.models import WordTimestamp


def test_build_and_write_subtitles(tmp_path: Path) -> None:
    words = [
        WordTimestamp(word="Hello", start=0.0, end=0.4),
        WordTimestamp(word="world", start=0.4, end=0.8),
        WordTimestamp(word="from", start=0.8, end=1.1),
        WordTimestamp(word="the", start=1.1, end=1.3),
        WordTimestamp(word="pipeline", start=1.3, end=2.0),
    ]
    writer = SubtitleWriter(max_words_per_cue=3)
    cues = writer.build_cues(words)
    assert len(cues) >= 2
    assert cues[0].start == 0.0
    assert cues[-1].end == 2.0

    srt_path = writer.write_srt(cues, tmp_path / "captions.srt")
    vtt_path = writer.write_vtt(cues, tmp_path / "captions.vtt")
    assert "-->" in srt_path.read_text(encoding="utf-8")
    assert vtt_path.read_text(encoding="utf-8").startswith("WEBVTT")
