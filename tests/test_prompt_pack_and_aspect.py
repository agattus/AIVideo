"""Tests for aspect-ratio helpers, quota pause, and visual prompt packs."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from youtube_pipeline.assets.aspect import (
    dimensions_for_aspect,
    label_for_aspect,
    normalize_aspect_ratio,
)
from youtube_pipeline.assets.prompt_pack import missing_scene_ids, write_visual_prompt_pack
from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.exceptions import QuotaExceededError
from youtube_pipeline.models import (
    AspectRatio,
    PipelineRequest,
    PipelineResult,
    SceneData,
    VideoScript,
    VisualStyle,
)


def _script() -> VideoScript:
    return VideoScript(
        title="Quota Demo",
        full_script="One. Two.",
        style="cinematic",
        scenes=[
            SceneData(
                scene_id=0,
                script_text="One.",
                visual_prompt="epic ocean wide shot, continuous character design",
                keywords=["ocean"],
                duration=2.0,
            ),
            SceneData(
                scene_id=1,
                script_text="Two.",
                visual_prompt="stormy mountain ridge, continuous character design",
                keywords=["mountain"],
                duration=2.0,
            ),
        ],
    )


def _color_jpg(path: Path, color: tuple[int, int, int] = (40, 120, 200)) -> None:
    Image.new("RGB", (64, 64), color).save(path, format="JPEG", quality=90)


def test_aspect_ratio_aliases_and_dimensions() -> None:
    assert normalize_aspect_ratio("shorts") == "9:16"
    assert normalize_aspect_ratio("youtube") == "16:9"
    assert normalize_aspect_ratio(AspectRatio.SQUARE) == "1:1"
    assert dimensions_for_aspect("9:16") == (1080, 1920)
    assert dimensions_for_aspect("16:9") == (1920, 1080)
    assert "Shorts" in label_for_aspect("9:16")


def test_write_visual_prompt_pack_marks_pending(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    _color_jpg(assets / "scene_00.jpg")
    pack = write_visual_prompt_pack(
        tmp_path,
        _script(),
        aspect_ratio="9:16",
        pending_scene_ids=[1],
        reason="Daily limit hit",
    )
    assert pack["aspect_ratio"] == "9:16"
    assert pack["width"] == 1080
    assert pack["height"] == 1920
    assert pack["pending_scene_ids"] == [1]
    assert (tmp_path / "visual_prompts.json").exists()
    assert (tmp_path / "VISUAL_PROMPTS.md").exists()
    assert (assets / "scene_01.prompt.txt").exists()
    md = (tmp_path / "VISUAL_PROMPTS.md").read_text(encoding="utf-8")
    assert "9:16" in md
    assert "scene_01.jpg" in md


def test_acquire_all_stops_on_quota_and_sets_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.IMAGEN,
        gemini_api_key="test-key",
    )
    service = AssetService(settings)
    calls: list[int] = []

    def fake_fetch(scene, output_dir, *, style="cinematic", aspect_ratio="16:9"):
        calls.append(scene.scene_id)
        if scene.scene_id == 0:
            from youtube_pipeline.models import MediaAsset

            path = Path(output_dir) / "scene_00.jpg"
            _color_jpg(path)
            return MediaAsset(
                scene_id=0,
                path=str(path),
                source="imagen",
                media_type="image",
                width=1920,
                height=1080,
            )
        raise QuotaExceededError("429 daily limit exceeded")

    monkeypatch.setattr(service, "fetch_for_scene", fake_fetch)
    assets = service.acquire_all(_script(), tmp_path / "assets", aspect_ratio="16:9")
    assert len(assets) == 1
    assert service.quota_hit is True
    assert service.pending_scene_ids == [1]
    assert calls == [0, 1]


def test_orchestrator_pauses_for_awaiting_assets(tmp_path: Path) -> None:
    from config.settings import Settings
    from youtube_pipeline.audio.tts import TTSResult
    from youtube_pipeline.models import MediaAsset, WordTimestamp
    from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

    class FakeScript:
        def generate(self, request):
            return _script().model_copy(update={"style": request.style.value})

    class FakeAudio:
        def synthesize(self, script, output_dir, *, voice=None):
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            audio = output_dir / "voiceover.mp3"
            audio.write_bytes(b"fake")
            timed = script.model_copy(
                update={
                    "scenes": [s.model_copy(update={"duration": 2.0}) for s in script.scenes]
                }
            )
            return TTSResult(
                audio_path=audio,
                duration_seconds=4.0,
                script=timed,
                word_timestamps=[
                    WordTimestamp(word="One", start=0.0, end=2.0),
                    WordTimestamp(word="Two", start=2.0, end=4.0),
                ],
                timing={"total_duration": 4.0},
            )

    class FakeAssets:
        def __init__(self):
            self.quota_hit = True
            self.pending_scene_ids = [1]
            self.quota_message = "daily limit"

        def acquire_all(self, script, output_dir, *, aspect_ratio="16:9"):
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / "scene_00.jpg"
            _color_jpg(path)
            return [
                MediaAsset(
                    scene_id=0,
                    path=str(path),
                    source="imagen",
                    media_type="image",
                )
            ]

        def fetch_bgm(self, style, output_dir):
            return None

    class BoomComposer:
        def compose(self, *args, **kwargs):
            raise AssertionError("compose must not run while awaiting assets")

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        gemini_api_key="x",
    )
    orch = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=FakeScript(),  # type: ignore[arg-type]
        audio_engine=FakeAudio(),  # type: ignore[arg-type]
        asset_service=FakeAssets(),  # type: ignore[arg-type]
        video_composer=BoomComposer(),  # type: ignore[arg-type]
    )
    result = orch.run(
        PipelineRequest(
            idea="Quota story",
            style=VisualStyle.CINEMATIC,
            aspect_ratio=AspectRatio.VERTICAL,
            output_name="quota-story",
        )
    )
    assert result.status == "awaiting_assets"
    assert result.metadata["aspect_ratio"] == "9:16"
    assert 1 in result.metadata["pending_scene_ids"]
    assert Path(result.metadata["visual_prompts_md"]).exists()
    assert "continue" in result.metadata["continue_command"]


def test_continue_from_run_compiles_after_reupload(tmp_path: Path) -> None:
    from config.settings import Settings
    from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

    run_dir = tmp_path / "run"
    assets = run_dir / "assets"
    audio = run_dir / "audio"
    assets.mkdir(parents=True)
    audio.mkdir(parents=True)
    script = _script()
    request = PipelineRequest(
        idea="Continue story",
        style=VisualStyle.CINEMATIC,
        aspect_ratio=AspectRatio.VERTICAL,
        output_name="continue-story",
    )
    (run_dir / "request.json").write_text(request.model_dump_json(), encoding="utf-8")
    (run_dir / "script_timed.json").write_text(script.model_dump_json(), encoding="utf-8")
    (run_dir / "script.json").write_text(script.model_dump_json(), encoding="utf-8")
    (audio / "voiceover.mp3").write_bytes(b"fake-audio")
    _color_jpg(assets / "scene_00.jpg")
    _color_jpg(assets / "scene_01.jpg", (200, 80, 40))

    class FakeComposer:
        def __init__(self):
            self.width = 0
            self.height = 0
            self.enable_ken_burns = True
            self.burn_captions = True

        def compose(self, script, audio_path, assets_dir, output_path):
            Path(output_path).write_bytes(b"mp4")
            return PipelineResult(
                video_path=str(Path(output_path).resolve()),
                status="success",
                metadata={"title": script.title},
            )

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        gemini_api_key="x",
        openai_api_key="x",
    )
    composer = FakeComposer()

    class _Unused:
        pass

    orch = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=_Unused(),  # type: ignore[arg-type]
        audio_engine=_Unused(),  # type: ignore[arg-type]
        asset_service=_Unused(),  # type: ignore[arg-type]
        video_composer=composer,  # type: ignore[arg-type]
    )
    result = orch.continue_from_run(run_dir)
    assert result.status == "success"
    assert result.video_path.endswith(".mp4")
    assert result.metadata["aspect_ratio"] == "9:16"
    assert Path(result.video_path).exists()


def test_missing_scene_ids_detects_blank(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    _color_jpg(assets / "scene_00.jpg")
    Image.new("RGB", (64, 64), (0, 0, 0)).save(assets / "scene_01.jpg", format="JPEG")
    assert missing_scene_ids(_script(), assets) == [1]


def test_generate_gemini_image_uses_requested_aspect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.IMAGEN,
        gemini_api_key="test-gemini-key",
    )
    service = AssetService(settings)
    jpeg_buf = __import__("io").BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(jpeg_buf, format="JPEG")
    jpeg = jpeg_buf.getvalue()
    captured: dict = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            captured["aspect_ratio"] = config.image_config.aspect_ratio
            return SimpleNamespace(
                parts=[SimpleNamespace(inline_data=SimpleNamespace(data=jpeg), as_image=None)],
                candidates=[],
            )

    class _FakeClient:
        def __init__(self, *, api_key: str):
            self.models = _FakeModels()

    import sys

    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        ImageConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        GenerateImagesConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    fake_genai = SimpleNamespace(Client=_FakeClient, types=fake_types)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    raw = service._generate_imagen(
        "vertical hero shot",
        model="gemini-2.5-flash-image",
        aspect_ratio="9:16",
    )
    assert raw == jpeg
    assert captured["aspect_ratio"] == "9:16"
