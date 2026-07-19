from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from youtube_pipeline.assets.provider import AssetService, STYLE_PROMPT_SUFFIX
from youtube_pipeline.models import SceneData, VideoScript


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _scene(scene_id: int = 0) -> SceneData:
    return SceneData(
        scene_id=scene_id,
        script_text="The ocean stretches forever.",
        visual_prompt="Wide aerial of a turquoise ocean at sunrise",
        keywords=["ocean", "aerial", "sunrise"],
        duration=3.0,
    )


def test_style_augmented_prompt_appends_cinematic_suffix() -> None:
    prompt = AssetService._style_augmented_prompt(
        "A lone lighthouse on a cliff",
        "cinematic",
    )
    assert "lone lighthouse" in prompt
    assert "cinematic lighting" in prompt
    assert STYLE_PROMPT_SUFFIX["cinematic"].split(",")[0] in prompt


def test_pexels_video_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        pexels_api_key="pexels-test",
        openai_api_key="openai-test",
    )
    service = AssetService(settings)

    video_payload = {
        "videos": [
            {
                "width": 1920,
                "height": 1080,
                "duration": 8,
                "user": {"name": "Ada"},
                "video_files": [
                    {
                        "width": 1920,
                        "height": 1080,
                        "file_type": "video/mp4",
                        "link": "https://example.com/clip.mp4",
                    }
                ],
            }
        ]
    }

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            if "videos/search" in url:
                return _FakeResponse(200, video_payload)
            if url.endswith(".mp4"):
                return _FakeResponse(200, content=b"fake-mp4-bytes")
            return _FakeResponse(404, {"error": "missing"})

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    asset = service.fetch_for_scene(_scene(0), tmp_path, style="cinematic")
    assert asset.source == "pexels_video"
    assert asset.media_type == "video"
    assert Path(asset.path).name == "scene_00.mp4"
    assert Path(asset.path).read_bytes() == b"fake-mp4-bytes"


def test_fallback_to_dalle_when_pexels_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        pexels_api_key="pexels-test",
        openai_api_key="openai-test",
        openai_image_model="dall-e-3",
    )
    service = AssetService(settings)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            # Empty video + image results force DALL·E fallback.
            if "videos/search" in url:
                return _FakeResponse(200, {"videos": []})
            if "v1/search" in url:
                return _FakeResponse(200, {"photos": []})
            return _FakeResponse(404, {})

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)
    monkeypatch.setattr(
        service,
        "_generate_dalle",
        lambda prompt: b"png-bytes",
    )

    asset = service.fetch_for_scene(_scene(1), tmp_path, style="cinematic")
    assert asset.source == "openai_dalle3"
    assert Path(asset.path).name == "scene_01.png"
    assert Path(asset.path).read_bytes() == b"png-bytes"


def test_acquire_all_writes_sequential_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        pexels_api_key="pexels-test",
        openai_api_key="openai-test",
    )
    service = AssetService(settings)

    script = VideoScript(
        title="Oceans",
        full_script="One. Two.",
        style="cinematic",
        scenes=[_scene(0), _scene(1).model_copy(update={"scene_id": 1, "script_text": "Two."})],
    )

    def fake_fetch(scene, output_dir, *, style="cinematic"):
        from youtube_pipeline.models import MediaAsset

        path = Path(output_dir) / f"scene_{scene.scene_id:02d}.jpg"
        path.write_bytes(b"img")
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(path),
            source="pexels_image",
            media_type="image",
        )

    monkeypatch.setattr(service, "fetch_for_scene", fake_fetch)
    assets = service.acquire_all(script, tmp_path / "assets")
    names = sorted(Path(a.path).name for a in assets)
    assert names == ["scene_00.jpg", "scene_01.jpg"]
