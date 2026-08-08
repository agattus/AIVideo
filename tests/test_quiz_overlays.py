from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from config.settings import Settings
from youtube_pipeline.models import BeatType, SceneData, VideoScript
from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer
from youtube_pipeline.video import quiz_overlays
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


def test_render_question_card_draws_emoji_not_tofu_boxes(tmp_path: Path) -> None:
    """Emoji clues must use a color emoji font (Segoe UI Emoji), not Arial tofu."""
    scene = _scene(
        BeatType.QUESTION,
        question="Guess the Song: \U0001f3b5\U0001f451",
        choices=["Starman", "Starboy"],
        answer="Starboy",
    )
    path = render_quiz_card(
        scene,
        dest=tmp_path / "emoji.png",
        width=1080,
        height=1920,
        countdown=None,
    )
    with Image.open(path) as image:
        # Color emoji pixels are not near-white/near-black tofu rectangles only.
        pixels = list(image.getdata())
        colorful = sum(
            1
            for r, g, b, a in pixels
            if a > 200 and max(r, g, b) - min(r, g, b) > 40
        )
        assert colorful > 50, "Expected colored emoji glyphs in quiz card"


def test_render_quiz_card_uses_requested_language_font(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_languages: list[str] = []
    monkeypatch.setattr(
        quiz_overlays,
        "caption_font_for_language",
        lambda language: requested_languages.append(language) or None,
    )

    render_quiz_card(
        _scene(BeatType.QUESTION),
        dest=tmp_path / "telugu.png",
        width=360,
        height=640,
        countdown=None,
        language="te",
    )

    assert requested_languages
    assert set(requested_languages) == {"te"}


@pytest.mark.parametrize("beat_type", [BeatType.QUESTION, BeatType.TIMER, BeatType.CTA])
def test_non_reveal_cards_never_draw_answer_or_explanation(
    beat_type: BeatType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drawn_text: list[str] = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn_text.append(str(text))
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    render_quiz_card(
        _scene(
            beat_type,
            answer="FORBIDDEN ANSWER",
            explain="FORBIDDEN EXPLANATION",
        ),
        dest=tmp_path / f"{beat_type.value}.png",
        width=720,
        height=1280,
        countdown=7,
    )

    assert "FORBIDDEN ANSWER" not in drawn_text
    assert "FORBIDDEN EXPLANATION" not in drawn_text


def test_reveal_card_draws_answer_and_explanation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drawn_text: list[str] = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn_text.append(str(text))
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    render_quiz_card(
        _scene(
            BeatType.REVEAL,
            answer="VISIBLE ANSWER",
            explain="VISIBLE EXPLANATION",
        ),
        dest=tmp_path / "reveal-text.png",
        width=720,
        height=1280,
        countdown=None,
    )

    assert "VISIBLE ANSWER" in drawn_text
    assert "VISIBLE EXPLANATION" in drawn_text


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


def test_composer_skips_burned_captions_on_quiz_overlay_beats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        burn_captions=True,
    )
    image = tmp_path / "scene.jpg"
    Image.new("RGB", (360, 640), (20, 40, 80)).save(image)
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"ID3")
    scenes = [
        _scene(BeatType.HOOK, scene_id=0, script_text="Intro"),
        _scene(BeatType.QUESTION, scene_id=1, script_text="Question caption"),
    ]
    script = VideoScript(
        title="Quiz",
        full_script="Intro Question caption",
        style="cinematic",
        format="quizverse",
        quiz_mode="comment",
        scenes=scenes,
    )
    captured: dict[BeatType, list[tuple[str, float, float]]] = {}

    monkeypatch.setattr(composer, "_probe_duration", lambda _path: 2.0)
    monkeypatch.setattr(composer, "_aligned_scene_durations", lambda *_args: [1.0, 1.0])
    monkeypatch.setattr(composer, "_allocate_scene_frames", lambda _durations: [24, 24])
    monkeypatch.setattr(composer, "_resolve_scene_image", lambda *_args: image)
    monkeypatch.setattr(
        "youtube_pipeline.video.ffmpeg_composer.scene_caption_timeline",
        lambda text, **_kwargs: [(text, 0.0, 1.0)],
    )

    def fake_render(_image, dest, *, scene, caption_cues, **_kwargs):
        captured[scene.beat_type] = caption_cues
        dest.write_bytes(b"clip")

    monkeypatch.setattr(composer, "_render_scene_clip", fake_render)
    monkeypatch.setattr(
        composer,
        "_concat_clips",
        lambda _clips, dest, **_kwargs: dest.write_bytes(b"video"),
    )
    monkeypatch.setattr(
        composer,
        "_mux_audio",
        lambda _video, _audio, dest, **_kwargs: dest.write_bytes(b"output"),
    )

    composer.compose(script, audio, tmp_path, tmp_path / "quiz.mp4")

    assert captured[BeatType.HOOK] == [("Intro", 0.0, 1.0)]
    assert captured[BeatType.QUESTION] == []


def test_composer_threads_language_into_quiz_overlay_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    base = tmp_path / "base.mp4"
    base.write_bytes(b"base")
    languages: list[str] = []

    def fake_render(
        beat,
        *,
        width,
        height,
        t_within_beat,
        language,
        dest_dir,
    ):
        languages.append(language)
        png = dest_dir / "overlay.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (width, height)).save(png)
        return png

    def fake_run(cmd: list[str], *, label: str) -> None:
        Path(cmd[-1]).write_bytes(b"video")

    monkeypatch.setattr(
        "youtube_pipeline.video.ffmpeg_composer.render_quiz_overlay_png",
        fake_render,
    )
    monkeypatch.setattr(composer, "_run", fake_run)

    composer._overlay_quiz_card(
        base,
        tmp_path / "dest.mp4",
        scene=_scene(BeatType.QUESTION),
        duration=1.0,
        work_dir=tmp_path / "overlay",
        language="te",
    )

    assert languages == ["te"]


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
