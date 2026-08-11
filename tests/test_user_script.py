"""Bring-your-own-script ingest parsers and quality no-rewrite."""

from __future__ import annotations

import json

import pytest

from youtube_pipeline.models import (
    PipelineRequest,
    QuizMode,
    VideoFormat,
    VisualStyle,
)
from youtube_pipeline.quality.script_review import run_script_quality_gate
from youtube_pipeline.quality.models import ScriptReview
from youtube_pipeline.script_engine.user_script import (
    enrich_visuals,
    ingest_user_script,
)


def _req(**kwargs) -> PipelineRequest:
    base = dict(
        idea="Custom film",
        format=VideoFormat.NARRATIVE,
        style=VisualStyle.CINEMATIC,
        target_duration_seconds=60,
        max_scenes=6,
        script_source="provided",
        language="en",
    )
    base.update(kwargs)
    return PipelineRequest(**base)


def test_narrative_blank_line_split():
    text = "Hook line one.\n\nMiddle beat here.\n\nStrong ending now."
    script = ingest_user_script(
        _req(user_script_text=text, max_scenes=8),
        enrich=False,
    )
    assert len(script.scenes) == 3
    assert script.scenes[0].script_text == "Hook line one."
    assert script.scenes[2].script_text == "Strong ending now."


def test_dialogue_name_colon_parse_and_pad_cast():
    text = "Alex: Hello there.\nSam: Hi back.\nAlex: Let's go."
    script = ingest_user_script(
        _req(format=VideoFormat.DIALOGUE, user_script_text=text, max_scenes=12),
        enrich=False,
    )
    assert script.format == "dialogue"
    assert len(script.lines) == 3
    assert script.lines[0]["text"] == "Hello there."
    assert len(script.cast) == 3  # padded to assign_voices requirement
    assert len(script.scenes) == 3


def test_quiz_block_parse():
    text = (
        "Q: Which planet is red?\n"
        "Choices: Earth | Mars | Venus\n"
        "A: Mars\n"
        "Explain: Iron oxide.\n\n"
        "Q: How many moons does Earth have?\n"
        "A: One"
    )
    script = ingest_user_script(
        _req(
            format=VideoFormat.QUIZVERSE,
            quiz_mode=QuizMode.REVEAL,
            question_count=2,
            user_script_text=text,
            max_scenes=20,
        ),
        enrich=False,
    )
    assert script.format == "quizverse"
    assert len(script.questions_raw) == 2
    assert script.questions_raw[0]["answer"] == "Mars"
    assert "Mars" in script.questions_raw[0]["choices"]


def test_narrative_json_path():
    payload = {
        "title": "My Title",
        "scenes": [
            {"script_text": "First spoken line.", "visual_prompt": "Foggy pier"},
            {"narration": "Second spoken line.", "visual_prompt": "City night"},
        ],
    }
    script = ingest_user_script(
        _req(user_script_json=payload, max_scenes=8),
        enrich=False,
    )
    assert script.title == "My Title"
    assert [s.script_text for s in script.scenes] == [
        "First spoken line.",
        "Second spoken line.",
    ]


def test_enrich_does_not_mutate_spoken_words():
    script = ingest_user_script(
        _req(user_script_text="Alpha sentence.\n\nBeta sentence."),
        enrich=False,
    )
    before = [s.script_text for s in script.scenes]

    def fake_llm(user_prompt: str, *, system_prompt: str) -> str:
        del user_prompt, system_prompt
        return json.dumps(
            {
                "title": "Enriched",
                "scenes": [
                    {"scene_id": 0, "visual_prompt": "New visual A"},
                    {"scene_id": 1, "visual_prompt": "New visual B"},
                ],
            }
        )

    enriched = enrich_visuals(script, _req(user_script_text="x"), llm_call=fake_llm)
    assert [s.script_text for s in enriched.scenes] == before
    assert enriched.title == "Enriched"
    assert "New visual A" in enriched.scenes[0].visual_prompt


def test_quality_gate_skips_rewrite_when_disallowed():
    script = ingest_user_script(
        _req(user_script_text="Keep these exact words forever.\n\nAnd these too."),
        enrich=False,
    )
    calls = {"rewrite": 0}

    def critique(candidate, request):
        del candidate, request
        return ScriptReview(
            status="needs_approval",
            scores={
                "idea_fit": 2,
                "hook": 2,
                "ending": 2,
                "pacing_emotion": 2,
                "format_rules": 2,
            },
            issues=["weak hook"],
        )

    def rewrite(candidate, request, review):
        del request, review
        calls["rewrite"] += 1
        return candidate

    out, review = run_script_quality_gate(
        script,
        _req(user_script_text="x"),
        critique_fn=critique,
        rewrite_fn=rewrite,
        allow_rewrite=False,
    )
    assert calls["rewrite"] == 0
    assert out.scenes[0].script_text == "Keep these exact words forever."
    assert review.status == "needs_approval"
    assert review.retries == 0
