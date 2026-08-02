from pathlib import Path

from PIL import Image

from config.settings import Settings
from youtube_pipeline.models import BeatType, SceneData
from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer
from youtube_pipeline.video.quiz_overlays import (
    render_quiz_card,
    render_quiz_overlay_png,
)


def _scene(beat_type: BeatType, **overrides: object) -> SceneData:
    values: dict[str, object] = {
        "scene_id": 0,
        "script_text": "" if beat_type == BeatType.TIMER else "Quiz",
        "visual_prompt": "background",
        "beat_type": beat_type,
        "hold_seconds": 5,
        "question": "Who is the king of the Greek gods?",
        "choices": ["Apollo", "Zeus"],
        "answer": "Zeus",
        "explain": "Zeus rules Mount Olympus.",
    }
    values.update(overrides)
    return SceneData(**values)


def test_render_question_card(tmp_path: Path) -> None:
    scene = _scene(BeatType.QUESTION)

    path = render_quiz_card(
        scene,
        dest=tmp_path / "q.png",
        width=1080,
        height=1920,
        countdown=None,
    )

    assert path.exists()
    assert path.stat().st_size > 500
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.size == (1080, 1920)
        assert image.getbbox() is not None


def test_render_countdown(tmp_path: Path) -> None:
    scene = _scene(BeatType.TIMER, hold_seconds=10)

    path = render_quiz_card(
        scene,
        dest=tmp_path / "t.png",
        width=1080,
        height=1920,
        countdown=7,
    )

    assert path.exists()
    assert path.stat().st_size > 500


def test_render_reveal_and_cta_cards(tmp_path: Path) -> None:
    reveal = render_quiz_card(
        _scene(BeatType.REVEAL),
        dest=tmp_path / "reveal.png",
        width=720,
        height=1280,
        countdown=None,
    )
    cta = render_quiz_card(
        _scene(
            BeatType.CTA,
            answer="DO NOT SHOW",
            explain="DO NOT SHOW",
        ),
        dest=tmp_path / "cta.png",
        width=720,
        height=1280,
        countdown=None,
    )

    assert reveal.stat().st_size > 500
    assert cta.stat().st_size > 500
    assert reveal.read_bytes() != cta.read_bytes()


def test_time_based_overlay_uses_remaining_whole_seconds(
    tmp_path: Path,
) -> None:
    scene = _scene(BeatType.TIMER, scene_id=3, hold_seconds=4)

    start = render_quiz_overlay_png(
        scene,
        width=360,
        height=640,
        t_within_beat=0.0,
        dest_dir=tmp_path,
    )
    later = render_quiz_overlay_png(
        scene,
        width=360,
        height=640,
        t_within_beat=1.2,
        dest_dir=tmp_path,
    )

    assert start is not None
    assert later is not None
    assert start.name.endswith("_4.png")
    assert later.name.endswith("_3.png")
    assert start.exists()
    assert later.exists()


def test_timer_scene_burns_one_overlay_per_remaining_second(
    tmp_path: Path,
    monkeypatch,
) -> None:
    composer = FFmpegComposer(
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
    image = tmp_path / "scene.jpg"
    Image.new("RGB", (360, 640), (20, 40, 80)).save(image)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, label: str) -> None:
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")

    monkeypatch.setattr(composer, "_run", fake_run)
    dest = tmp_path / "clip.mp4"
    composer._render_scene_clip(
        image,
        dest,
        duration=3.2,
        frames=77,
        scene_index=0,
        scene=_scene(BeatType.TIMER, hold_seconds=3.2),
        caption_cues=[],
        work_dir=tmp_path / "overlays",
    )

    overlay_commands = [cmd for cmd in calls if "-filter_complex" in cmd]
    assert len(overlay_commands) == 1
    command = overlay_commands[0]
    assert sum(part.endswith(".png") for part in command) == 4
    graph = command[command.index("-filter_complex") + 1]
    assert "between(t,0.000,1.000)" in graph
    assert "between(t,3.000,3.200)" in graph
    assert dest.exists()


def test_quiz_overlay_failure_keeps_base_scene_clip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    composer = FFmpegComposer(
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
    image = tmp_path / "scene.jpg"
    Image.new("RGB", (360, 640), (20, 40, 80)).save(image)

    def fake_run(cmd: list[str], *, label: str) -> None:
        if label == "quiz-overlay":
            raise RuntimeError("overlay unavailable")
        Path(cmd[-1]).write_bytes(b"base video")

    monkeypatch.setattr(composer, "_run", fake_run)
    dest = tmp_path / "clip.mp4"
    composer._render_scene_clip(
        image,
        dest,
        duration=1.0,
        frames=24,
        scene_index=0,
        scene=_scene(BeatType.QUESTION),
        caption_cues=[],
        work_dir=tmp_path / "overlays",
    )

    assert dest.read_bytes() == b"base video"
