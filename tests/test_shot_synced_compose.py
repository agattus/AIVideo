def test_edge_fade_shorter_for_dialogue_vertical():
    from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer

    composer = FFmpegComposer(aspect_ratio="9:16")

    edge = composer._clip_edge_fade_seconds(
        4.0,
        format="dialogue",
        aspect_ratio="9:16",
    )
    wide = composer._clip_edge_fade_seconds(
        4.0,
        format="narrative",
        aspect_ratio="16:9",
    )

    assert edge <= 0.22
    assert wide >= edge


def test_concat_clips_does_not_call_overlapping_xfade(tmp_path, monkeypatch):
    """Overlapping xfade desyncs VO from cards; hard concat must be used."""
    from pathlib import Path

    from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer

    composer = FFmpegComposer(aspect_ratio="16:9")
    called: list[str] = []

    def _fake_run(cmd, label=""):
        called.append(label)
        Path(cmd[-1]).write_bytes(b"\x00")

    monkeypatch.setattr(composer, "_run", _fake_run)
    monkeypatch.setattr(
        composer,
        "_concat_clips_xfade",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("xfade must not run")),
    )

    clips = []
    for i in range(3):
        p = tmp_path / f"c{i}.mp4"
        p.write_bytes(b"clip")
        clips.append(p)
    dest = tmp_path / "out.mp4"
    composer._concat_clips(clips, dest, durations=[5.0, 5.0, 5.0])
    assert "concat" in called
    assert dest.exists()
