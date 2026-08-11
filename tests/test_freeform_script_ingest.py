"""Freeform creative-brief ingest with format auto-detection."""

from __future__ import annotations

import json

import pytest

from youtube_pipeline.models import PipelineRequest, VideoFormat, VisualStyle
from youtube_pipeline.script_engine.user_script import ingest_user_script


def _req(**kwargs) -> PipelineRequest:
    base = dict(
        idea="Sanatri Imaginings mythology short",
        format=VideoFormat.NARRATIVE,
        style=VisualStyle.CINEMATIC,
        target_duration_seconds=50,
        max_scenes=10,
        script_source="provided",
        language="en",
    )
    base.update(kwargs)
    return PipelineRequest(**base)


_MATSYA_BRIEF = """
## Today's Short: Why Did Lord Vishnu Become a Tiny Fish?

**Narrator:**
"Why would the Supreme Lord Vishnu… choose to become a tiny fish?"

**Fish:**
"King… please save me."

**Vishnu:**
"I am Vishnu. A great flood is coming."

### Visual Plan
1. Cosmic Vishnu to tiny golden fish
2. Ancient river at sunrise
3. Colossal Matsya emerging
"""


def test_freeform_multi_speaker_detects_dialogue():
    def fake_llm(user_prompt: str, *, system_prompt: str) -> str:
        del user_prompt, system_prompt
        return json.dumps(
            {
                "format": "dialogue",
                "title": "Why Did Lord Vishnu Become a Tiny Fish?",
                "style": "cinematic",
                "cast": [
                    {"id": "narrator", "name": "Narrator", "gender_hint": "male"},
                    {"id": "fish", "name": "Fish", "gender_hint": ""},
                    {"id": "vishnu", "name": "Vishnu", "gender_hint": "male"},
                ],
                "lines": [
                    {
                        "speaker_id": "narrator",
                        "text": "Why would the Supreme Lord Vishnu choose to become a tiny fish?",
                        "visual_prompt": "Cosmic Vishnu transforming into a tiny golden fish",
                    },
                    {
                        "speaker_id": "fish",
                        "text": "King… please save me.",
                        "visual_prompt": "Tiny golden fish in cupped hands",
                    },
                    {
                        "speaker_id": "vishnu",
                        "text": "I am Vishnu. A great flood is coming.",
                        "visual_prompt": "Colossal golden Matsya emerging from the ocean",
                    },
                ],
            }
        )

    script = ingest_user_script(
        _req(user_script_text=_MATSYA_BRIEF, format=VideoFormat.NARRATIVE),
        llm_call=fake_llm,
        enrich=False,
    )
    assert script.format == "dialogue"
    assert len(script.cast) == 3
    assert script.lines[0]["text"].startswith("Why would the Supreme Lord Vishnu")
    assert "golden fish" in script.scenes[0].visual_prompt.lower()


def test_freeform_narrative_payload():
    def fake_llm(user_prompt: str, *, system_prompt: str) -> str:
        del user_prompt, system_prompt
        return json.dumps(
            {
                "format": "narrative",
                "title": "River Morning",
                "scenes": [
                    {
                        "script_text": "Beside a sacred river, a king prayed.",
                        "visual_prompt": "Ancient Indian river at sunrise",
                    },
                    {
                        "script_text": "A tiny golden fish appeared in his hands.",
                        "visual_prompt": "Close-up golden fish in water",
                    },
                ],
            }
        )

    script = ingest_user_script(
        _req(user_script_text="A king and a fish by the river."),
        llm_call=fake_llm,
        enrich=False,
    )
    assert script.format == "narrative"
    assert len(script.scenes) == 2
    assert script.scenes[0].script_text == "Beside a sacred river, a king prayed."


def test_freeform_falls_back_when_llm_fails():
    def boom(user_prompt: str, *, system_prompt: str) -> str:
        del user_prompt, system_prompt
        raise RuntimeError("quota")

    script = ingest_user_script(
        _req(user_script_text="First beat.\n\nSecond beat."),
        llm_call=boom,
        enrich=False,
    )
    assert script.format == "narrative"
    assert len(script.scenes) == 2
