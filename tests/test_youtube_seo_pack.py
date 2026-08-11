"""YouTube SEO pack generation and fallback."""

from __future__ import annotations

import json

from youtube_pipeline.models import AspectRatio, PipelineRequest, VideoFormat, VideoScript
from youtube_pipeline.seo.fallback import build_fallback_pack, clamp_title, resolve_pack_mode
from youtube_pipeline.seo.generator import generate_youtube_pack
from youtube_pipeline.seo.store import load_youtube_pack, save_youtube_pack


def _script(title: str, idea_bit: str) -> VideoScript:
    return VideoScript(
        title=title,
        full_script=f"{idea_bit}. Scene one. Scene two.",
        style="cinematic",
        scenes=[
            {
                "scene_id": 0,
                "script_text": f"{idea_bit} begins at the gate.",
                "visual_prompt": "gate at night",
                "duration": 4.0,
                "keywords": ["gate", "night"],
            },
            {
                "scene_id": 1,
                "script_text": f"{idea_bit} twists in the corridor.",
                "visual_prompt": "dark corridor",
                "duration": 5.0,
                "keywords": ["corridor"],
            },
        ],
    )


def _request(idea: str, *, aspect: AspectRatio = AspectRatio.LANDSCAPE) -> PipelineRequest:
    return PipelineRequest(
        idea=idea,
        style="cinematic",
        format=VideoFormat.NARRATIVE,
        aspect_ratio=aspect,
        language="en",
        target_duration_seconds=60,
    )


def test_resolve_pack_mode_shorts_for_vertical() -> None:
    assert resolve_pack_mode(AspectRatio.VERTICAL) == "shorts"
    assert resolve_pack_mode(AspectRatio.LANDSCAPE) == "longform"


def test_clamp_title_limits() -> None:
    long = "A" * 90
    assert len(clamp_title(long, mode="shorts")) <= 70
    assert len(clamp_title(long, mode="longform")) <= 100


def test_fallback_packs_are_unique_per_story() -> None:
    a = build_fallback_pack(_script("Matsya Rising", "Matsya"), _request("Matsya flood myth"))
    b = build_fallback_pack(
        _script("Lighthouse Vanish", "Lighthouse"),
        _request("Missing lighthouse keeper"),
    )
    assert a.description != b.description
    assert a.primary_title != b.primary_title
    assert "Matsya" in a.description
    assert "Lighthouse" in b.description


def test_shorts_fallback_includes_shorts_hashtag_and_no_chapters() -> None:
    pack = build_fallback_pack(
        _script("Quick Hook", "Quick"),
        _request("Quick story", aspect=AspectRatio.VERTICAL),
    )
    assert pack.mode == "shorts"
    assert any(h.lower() == "#shorts" for h in pack.hashtags)
    assert pack.chapters == []


def test_longform_fallback_builds_chapters() -> None:
    pack = build_fallback_pack(
        _script("Long Tale", "Long"),
        _request("Long tale"),
    )
    assert pack.mode == "longform"
    assert len(pack.chapters) >= 2
    assert pack.chapters[0].start_seconds == 0


def test_generate_uses_llm_json(monkeypatch) -> None:
    payload = {
        "primary_title": "The Gate That Should Stay Shut",
        "alt_titles": ["Why the Gate Opened", "Do Not Enter the Gate"],
        "description": "Hook line.\n\nSynopsis here.\n\nKeywords: gate, mystery\n\n#story",
        "tags": ["gate", "mystery", "story"],
        "hashtags": ["#mystery", "#story"],
        "pinned_comment": "Would you walk through?",
        "chapters": [{"start_seconds": 0, "label": "Hook"}, {"start_seconds": 4, "label": "Turn"}],
    }

    pack = generate_youtube_pack(
        _script("Old Title", "Gate"),
        _request("Forbidden gate"),
        llm_call=lambda user, system_prompt="": json.dumps(payload),
    )
    assert pack.source == "llm"
    assert pack.primary_title == "The Gate That Should Stay Shut"
    assert "Would you walk through?" in pack.pinned_comment
    assert len(pack.chapters) == 2


def test_generate_falls_back_when_llm_fails() -> None:
    def boom(user, system_prompt=""):
        raise RuntimeError("llm down")

    pack = generate_youtube_pack(
        _script("Fallback Title", "Fallback"),
        _request("Fallback idea"),
        llm_call=boom,
    )
    assert pack.source == "fallback"
    assert "Fallback" in pack.description


def test_store_roundtrip(tmp_path) -> None:
    pack = build_fallback_pack(_script("Store Me", "Store"), _request("Store idea"))
    save_youtube_pack(tmp_path, pack)
    loaded = load_youtube_pack(tmp_path)
    assert loaded is not None
    assert loaded.primary_title == pack.primary_title
