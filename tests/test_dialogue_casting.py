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
        "en-US-DavisNeural",
        "en-GB-RyanNeural",
        "en-AU-WilliamNeural",
        "en-IN-PrabhatNeural",
    }
    assert voice_map["b"] in {
        "en-US-JennyNeural",
        "en-US-AriaNeural",
        "en-US-SaraNeural",
        "en-GB-SoniaNeural",
        "en-AU-NatashaNeural",
        "en-IN-NeerjaNeural",
    }


def test_assign_voices_falls_back_to_language_default_when_catalog_is_sparse() -> None:
    cast = [
        {"id": "a", "name": "Arjun", "gender_hint": "male"},
        {"id": "b", "name": "Sita", "gender_hint": "female"},
        {"id": "c", "name": "Guide"},
    ]

    voice_map = assign_voices(cast, language="te-IN")

    assert voice_map == {
        "a": "te-IN-MohanNeural",
        "b": "te-IN-MohanNeural",
        "c": "te-IN-MohanNeural",
    }


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
