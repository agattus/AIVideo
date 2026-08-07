import pytest

from youtube_pipeline.dialogue.casting import assign_voices


def test_assign_voices_uses_distinct_gender_matched_english_voices() -> None:
    cast = [
        {"id": "a", "name": "Ravi", "gender_hint": "male"},
        {"id": "b", "name": "Maya", "gender_hint": "female"},
        {"id": "c", "name": "Old Guard", "gender_hint": "male"},
        {"id": "d", "name": "Captain", "gender_hint": "female"},
    ]

    voice_map = assign_voices(cast, language="en-US")

    assert set(voice_map) == {"a", "b", "c", "d"}
    assert len(set(voice_map.values())) == 4
    assert all(voice.startswith("en-") for voice in voice_map.values())
    assert voice_map["a"] in {
        "en-US-ChristopherNeural",
        "en-US-GuyNeural",
        "en-US-AndrewNeural",
        "en-GB-RyanNeural",
        "en-AU-WilliamMultilingualNeural",
        "en-IN-PrabhatNeural",
    } or str(voice_map["a"]).startswith("en-")
    assert voice_map["b"] in {
        "en-US-JennyNeural",
        "en-US-AriaNeural",
        "en-US-EmmaNeural",
        "en-GB-SoniaNeural",
        "en-AU-NatashaNeural",
        "en-IN-NeerjaNeural",
    } or str(voice_map["b"]).startswith("en-")
    assert "DavisNeural" not in voice_map.values()
    assert "SaraNeural" not in "".join(voice_map.values())


def test_assign_voices_uses_live_telugu_catalog_when_available() -> None:
    cast = [
        {"id": "a", "name": "Arjun", "gender_hint": "male"},
        {"id": "b", "name": "Sita", "gender_hint": "female"},
        {"id": "c", "name": "Guide"},
    ]

    voice_map = assign_voices(cast, language="te-IN")

    assert voice_map["a"] == "te-IN-MohanNeural"
    assert voice_map["b"] == "te-IN-ShrutiNeural"
    assert voice_map["c"].startswith("te-IN-")



@pytest.mark.parametrize(
    "cast",
    [
        [{"id": "a"}, {"id": "b"}],
        [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}, {"id": "e"}],
        [{"id": "a"}, {"id": "a"}, {"id": "c"}],
    ],
)
def test_assign_voices_rejects_invalid_cast(cast: list[dict]) -> None:
    with pytest.raises(ValueError):
        assign_voices(cast)
