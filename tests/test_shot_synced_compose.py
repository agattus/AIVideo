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
