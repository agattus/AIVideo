from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from config.settings import Settings
from youtube_pipeline.models import SceneData, VideoScript
from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer
from youtube_pipeline.video.nameplate_overlays import render_nameplate_png


def _composer(tmp_path: Path) -> FFmpegComposer:
    return FFmpegComposer(
        Settings(
            output_dir=tmp_path / "output",
            assets_cache_dir=tmp_path / "cache",
            _env_file=None,
        ),
        width=360,
        height=640,
        fps=24,
        burn_captions=False,
    )


def test_render_nameplate_png_creates_small_transparent_overlay(tmp_path: Path) -> None:
    """Catch nameplates becoming missing or full-frame quiz-style cards."""
    path = render_nameplate_png(
        "Maya",
        dest=tmp_path / "maya.png",
        width=1080,
        height=1920,
    )

    assert path.exists()
    assert path.stat().st_size > 200
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.width < 1080
        assert image.height < 1920 // 4
        assert image.getbbox() is not None


def test_render_nameplate_png_fits_long_name_inside_plate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch long speaker names being clipped by the compact plate boundary."""
    text_right_edges: list[tuple[float, int]] = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        box = self.textbbox(xy, text, font=kwargs.get("font"))
        text_right_edges.append((box[2], self._image.width))
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    render_nameplate_png(
        "Alexandria Montgomery-Singh",
        dest=tmp_path / "long-name.png",
        width=360,
        height=640,
    )

    assert text_right_edges
    assert all(right <= image_width for right, image_width in text_right_edges)


def test_composer_uses_each_line_timing_as_nameplate_enable_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch dialogue nameplates ignoring absolute TTS line windows."""
    composer = _composer(tmp_path)
    base = tmp_path / "base.mp4"
    base.write_bytes(b"base")
    calls: list[list[str]] = []
    rendered_names: list[str] = []

    def fake_render(name: str, *, dest: Path, width: int, height: int, language: str):
        rendered_names.append(name)
        Image.new("RGBA", (120, 40), (0, 0, 0, 128)).save(dest)
        return dest

    def fake_run(cmd: list[str], *, label: str) -> None:
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")

    monkeypatch.setattr(
        "youtube_pipeline.video.ffmpeg_composer.render_nameplate_png",
        fake_render,
    )
    monkeypatch.setattr(composer, "_run", fake_run)

    destination = tmp_path / "named.mp4"
    composer._overlay_dialogue_nameplates(
        base,
        destination,
        line_timings=[
            {"speaker_name": "Maya", "start": 1.25, "end": 2.75},
            {"speaker_name": "Ravi", "start": 2.75, "end": 4.0},
        ],
        work_dir=tmp_path / "nameplates",
        language="en",
    )

    assert rendered_names == ["Maya", "Ravi"]
    command = calls[0]
    graph = command[command.index("-filter_complex") + 1]
    assert "between(t,1.250,2.750)" in graph
    assert "between(t,2.750,4.000)" in graph
    assert destination.read_bytes() == b"video"


def test_compose_adds_nameplates_only_for_dialogue_with_line_timings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch compose dropping TTS line timings before final video mux."""
    composer = _composer(tmp_path)
    image = tmp_path / "scene.jpg"
    Image.new("RGB", (360, 640)).save(image)
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"ID3")
    script = VideoScript(
        title="Gate",
        full_script="Wait.",
        style="cinematic",
        format="dialogue",
        cast=[{"id": "maya", "name": "Maya"}],
        lines=[{"speaker_id": "maya", "speaker_name": "Maya", "text": "Wait."}],
        scenes=[
            SceneData(
                scene_id=0,
                script_text="Wait.",
                visual_prompt="A guarded gate",
                line_start=0,
                line_end=0,
            )
        ],
    )
    line_timings = [
        {"speaker_name": "Maya", "text": "Wait.", "start": 0.0, "end": 1.0}
    ]
    received: list[dict[str, object]] = []

    monkeypatch.setattr(composer, "_probe_duration", lambda _path: 1.0)
    monkeypatch.setattr(composer, "_resolve_scene_image", lambda *_args: image)
    monkeypatch.setattr(
        composer,
        "_render_scene_clip",
        lambda _image, dest, **_kwargs: dest.write_bytes(b"clip"),
    )
    monkeypatch.setattr(
        composer,
        "_concat_clips",
        lambda _clips, dest, **_kwargs: dest.write_bytes(b"silent"),
    )

    def fake_nameplates(base, dest, *, line_timings, **_kwargs):
        received.extend(line_timings)
        dest.write_bytes(base.read_bytes())

    monkeypatch.setattr(composer, "_overlay_dialogue_nameplates", fake_nameplates)
    monkeypatch.setattr(
        composer,
        "_mux_audio",
        lambda _video, _audio, dest, **_kwargs: dest.write_bytes(b"output"),
    )

    composer.compose(
        script,
        audio,
        tmp_path,
        tmp_path / "dialogue.mp4",
        timing={"lines": line_timings},
    )

    assert received == line_timings


def test_nameplate_overlay_failure_keeps_base_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch optional nameplate failures aborting video assembly."""
    composer = _composer(tmp_path)
    base = tmp_path / "base.mp4"
    base.write_bytes(b"assembled video")

    monkeypatch.setattr(
        "youtube_pipeline.video.ffmpeg_composer.render_nameplate_png",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("font unavailable")),
    )

    destination = tmp_path / "named.mp4"
    composer._overlay_dialogue_nameplates(
        base,
        destination,
        line_timings=[{"speaker_name": "Maya", "start": 0.0, "end": 1.0}],
        work_dir=tmp_path / "nameplates",
    )

    assert destination.read_bytes() == b"assembled video"
