from __future__ import annotations

import json
import re

import pytest

from config.settings import LLMProvider, Settings, TTSProvider
from youtube_pipeline.exceptions import ScriptGenerationError
from youtube_pipeline.models import PipelineRequest, VideoFormat
from youtube_pipeline.script_engine.generator import ScriptEngine
from youtube_pipeline.script_engine.schema import DIALOGUE_SCRIPT_SCHEMA


def _dialogue_payload() -> dict:
    return {
        "title": "కోట రహస్యం",
        "cast": [
            {"id": "ravi", "name": "రవి", "gender_hint": "male"},
            {"id": "maya", "name": "మాయ", "gender_hint": "female"},
            {"id": "guard", "name": "కాపలాదారు", "gender_hint": "male"},
        ],
        "lines": [
            {"speaker_id": "ravi", "text": "ఈ కోట తలుపు తెరిచి ఉంది."},
            {"speaker_id": "maya", "text": "నిన్న ఇది మూసి ఉంది."},
            {"speaker_id": "guard", "text": "లోపలికి వెళ్లకండి."},
            {"speaker_id": "ravi", "text": "ఎందుకు భయపడుతున్నారు?"},
            {"speaker_id": "guard", "text": "అక్కడ ఎవరో మేల్కొన్నారు."},
            {"speaker_id": "maya", "text": "ఆ శబ్దం మళ్లీ వచ్చింది."},
            {"speaker_id": "ravi", "text": "మనము నిజం తెలుసుకోవాలి."},
            {"speaker_id": "maya", "text": "అయితే కలిసి వెళ్దాం."},
        ],
        "visual_beats": [
            {
                "line_start": 0,
                "line_end": 1,
                "visual_prompt": "Ancient fortress gate standing open at midnight",
            },
            {
                "line_start": 2,
                "line_end": 3,
                "visual_prompt": "Nervous guard blocking two visitors",
            },
            {
                "line_start": 4,
                "line_end": 5,
                "visual_prompt": "Dark corridor with a distant moving shadow",
            },
            {
                "line_start": 6,
                "line_end": 7,
                "visual_prompt": "Three figures entering the fortress together",
            },
        ],
    }


def _dialogue_payload_with_line_count(line_count: int) -> dict:
    payload = _dialogue_payload()
    cast = payload["cast"]
    payload["lines"] = [
        {
            "speaker_id": cast[index % len(cast)]["id"],
            "text": f"Dialogue line {index}.",
            "visual_prompt": f"Unique cinematic shot for line {index}",
        }
        for index in range(line_count)
    ]
    payload.pop("visual_beats")
    return payload


def _engine() -> ScriptEngine:
    return ScriptEngine(
        Settings(
            gemini_api_key="gemini-test-key",
            llm_provider=LLMProvider.GEMINI,
            tts_provider=TTSProvider.EDGE_TTS,
            _env_file=None,
        )
    )


def _request() -> PipelineRequest:
    return PipelineRequest(
        idea="A mysterious fortress",
        format=VideoFormat.DIALOGUE,
        language="te",
    )


def test_dialogue_schema_resolves_every_local_reference() -> None:
    def resolve(pointer: str) -> object:
        assert pointer.startswith("#/")
        value: object = DIALOGUE_SCRIPT_SCHEMA
        for part in pointer[2:].split("/"):
            assert isinstance(value, dict)
            value = value[part.replace("~1", "/").replace("~0", "~")]
        return value

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                resolve(reference)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(DIALOGUE_SCRIPT_SCHEMA)


def test_dialogue_generate_expands_beats_assigns_voices_and_sets_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    calls: list[tuple[str, str]] = []

    def fake_llm(user_prompt: str, *, system_prompt: str) -> str:
        calls.append((user_prompt, system_prompt))
        return json.dumps(_dialogue_payload())

    monkeypatch.setattr(engine, "_call_llm", fake_llm)

    script = engine.generate(_request())

    assert script.format == "dialogue"
    assert len(script.cast) == 3
    assert len(script.lines) == 8
    assert len(script.scenes) == len(script.lines) == 8
    assert set(script.voice_map) == {"ravi", "maya", "guard"}
    assert script.lines[0]["speaker_name"] == "రవి"
    assert script.scenes[0].line_start == 0
    assert script.scenes[0].line_end == 0
    assert script.full_script == " ".join(line["text"] for line in script.lines)
    user_prompt, system_prompt = calls[0]
    for prompt in (user_prompt, system_prompt):
        assert "3 or 4" in prompt
        assert "8 to 16" in prompt
        assert "Telugu" in prompt
        assert "one visual per dialogue line" in prompt
        assert "line_start == line_end" in prompt
        assert "Multi-line visual beats are discouraged" in prompt
    assert "visual_prompt" in system_prompt
    assert "English" in system_prompt


def test_dialogue_duration_changes_generated_line_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    requested_line_counts: list[int] = []

    def fake_llm(user_prompt: str, *, system_prompt: str) -> str:
        match = re.search(r"exactly (\d+) dialogue lines", user_prompt)
        assert match is not None
        line_count = int(match.group(1))
        requested_line_counts.append(line_count)
        assert f"exactly {line_count} dialogue lines" in system_prompt
        return json.dumps(_dialogue_payload_with_line_count(line_count))

    monkeypatch.setattr(engine, "_call_llm", fake_llm)

    short = engine.generate(
        _request().model_copy(
            update={"target_duration_seconds": 30, "max_scenes": 16}
        )
    )
    long = engine.generate(
        _request().model_copy(
            update={"target_duration_seconds": 90, "max_scenes": 16}
        )
    )

    assert requested_line_counts == [8, 15]
    assert len(short.lines) == 8
    assert len(long.lines) == 15


def test_dialogue_generate_accepts_per_line_visual_prompts_without_beats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    payload = _dialogue_payload()
    payload.pop("visual_beats")
    for index, line in enumerate(payload["lines"]):
        line["visual_prompt"] = f"Unique cinematic shot for dialogue line {index}"

    monkeypatch.setattr(
        engine,
        "_call_llm",
        lambda *args, **kwargs: json.dumps(payload),
    )

    script = engine.generate(_request())

    assert len(script.scenes) == len(script.lines) == 8
    assert [
        scene.visual_prompt for scene in script.scenes
    ] == [
        f"Unique cinematic shot for dialogue line {index}"
        for index in range(8)
    ]


def test_dialogue_payload_validation_rejects_too_few_lines() -> None:
    from youtube_pipeline.script_engine.schema import validate_dialogue_script_payload

    payload = _dialogue_payload()
    payload["lines"] = payload["lines"][:7]

    with pytest.raises(ValueError, match="at least 8"):
        validate_dialogue_script_payload(payload)


def test_dialogue_generate_retries_invalid_payload_with_corrective_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    invalid = _dialogue_payload()
    invalid["lines"] = invalid["lines"][:7]
    responses = iter((invalid, _dialogue_payload()))
    user_prompts: list[str] = []

    def fake_llm(user_prompt: str, *, system_prompt: str) -> str:
        user_prompts.append(user_prompt)
        return json.dumps(next(responses))

    monkeypatch.setattr(engine, "_call_llm", fake_llm)

    script = engine.generate(_request())

    assert len(user_prompts) == 2
    assert "PREVIOUS RESPONSE WAS INVALID" in user_prompts[1]
    assert "4 to 6 visual beats" not in user_prompts[1]
    assert "visual_prompt on every line" in user_prompts[1]
    assert "line_start == line_end" in user_prompts[1]
    assert len(script.lines) == 8


def test_dialogue_generate_stops_after_three_invalid_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    invalid = _dialogue_payload()
    invalid["visual_beats"] = invalid["visual_beats"][:3]
    calls = 0

    def fake_llm(*args, **kwargs) -> str:
        nonlocal calls
        calls += 1
        return json.dumps(invalid)

    monkeypatch.setattr(engine, "_call_llm", fake_llm)

    with pytest.raises(
        ScriptGenerationError,
        match="Failed to produce valid dialogue JSON after 3 attempts",
    ):
        engine.generate(_request())
    assert calls == 3
