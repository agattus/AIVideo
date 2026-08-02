from __future__ import annotations

import json
from pathlib import Path

from config.settings import Settings
from youtube_pipeline.api import tasks
from youtube_pipeline.api.schemas import GenerateVideoRequest
from youtube_pipeline.assets.hitl_workspace import workspace_status
from youtube_pipeline.audio.tts import TTSResult
from youtube_pipeline.models import (
    BeatType,
    PipelineRequest,
    QuizMode,
    SceneData,
    VideoFormat,
    VideoScript,
)
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator


QUESTIONS = [
    {
        "question": "Who rules Olympus?",
        "choices": ["Apollo", "Zeus"],
        "answer": "Zeus",
        "explain": "Zeus is king of the gods.",
    }
]


def test_generate_request_accepts_quizverse() -> None:
    req = GenerateVideoRequest(
        idea="Greek gods quiz",
        format="quizverse",
        quiz_mode="comment",
        question_count=1,
        aspect_ratio="9:16",
    )

    assert req.format == "quizverse"
    assert req.quiz_mode == "comment"


def test_generate_request_defaults_to_narrative() -> None:
    req = GenerateVideoRequest(idea="Greek gods story")

    assert req.format == "narrative"
    assert req.quiz_mode is None
    assert req.question_count is None


def test_api_mapping_defaults_and_clamps_comment_quiz() -> None:
    request = tasks._build_pipeline_request(
        "job-1",
        {"idea": "Greek gods quiz", "format": "quizverse", "question_count": 99},
    )

    assert request.format == VideoFormat.QUIZVERSE
    assert request.quiz_mode == QuizMode.COMMENT
    assert request.question_count == 5


def test_api_mapping_accepts_pydantic_model_dump() -> None:
    payload = GenerateVideoRequest(
        idea="Greek gods quiz",
        format="quizverse",
        quiz_mode="comment",
        question_count=1,
    )

    request = tasks._build_pipeline_request("job-model", payload.model_dump())

    assert request.format == VideoFormat.QUIZVERSE
    assert request.quiz_mode == QuizMode.COMMENT
    assert request.question_count == 1


def test_api_mapping_clamps_nonpositive_question_count() -> None:
    payload = GenerateVideoRequest(
        idea="Greek gods quiz",
        format="quizverse",
        quiz_mode="comment",
        question_count=0,
    )

    request = tasks._build_pipeline_request("job-low", payload.model_dump())

    assert request.question_count == 1


def test_api_mapping_defaults_and_clamps_reveal_quiz() -> None:
    defaulted = tasks._build_pipeline_request(
        "job-2",
        {"idea": "Greek gods quiz", "format": "quizverse", "quiz_mode": "reveal"},
    )
    clamped = tasks._build_pipeline_request(
        "job-3",
        {
            "idea": "Greek gods quiz",
            "format": "quizverse",
            "quiz_mode": "reveal",
            "question_count": 99,
        },
    )
    lower_clamped = tasks._build_pipeline_request(
        "job-4",
        {
            "idea": "Greek gods quiz",
            "format": "quizverse",
            "quiz_mode": "reveal",
            "question_count": 0,
        },
    )

    assert defaulted.question_count == 5
    assert clamped.question_count == 15
    assert lower_clamped.question_count == 1


def test_api_mapping_ignores_quiz_fields_for_narrative() -> None:
    request = tasks._build_pipeline_request(
        "job-5",
        {
            "idea": "Greek gods story",
            "quiz_mode": "reveal",
            "question_count": 12,
        },
    )

    assert request.format == VideoFormat.NARRATIVE
    assert request.quiz_mode is None
    assert request.question_count is None


class _QuizScriptEngine:
    def generate(self, request: PipelineRequest) -> VideoScript:
        return VideoScript(
            title="Greek Gods Quiz",
            full_script="Who rules Olympus?",
            style="cinematic",
            format="quizverse",
            quiz_mode="comment",
            questions_raw=QUESTIONS,
            scenes=[
                SceneData(
                    scene_id=0,
                    script_text="Who rules Olympus?",
                    visual_prompt="Mount Olympus",
                    beat_type=BeatType.QUESTION,
                    quiz_index=0,
                    **QUESTIONS[0],
                )
            ],
        )


class _AudioEngine:
    def synthesize(
        self,
        script: VideoScript,
        output_dir: Path,
        *,
        voice: str | None = None,
    ) -> TTSResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "voiceover.mp3"
        audio_path.write_bytes(b"audio")
        return TTSResult(
            audio_path=audio_path,
            duration_seconds=2.0,
            script=script,
            word_timestamps=[],
            timing={"total_duration": 2.0, "scenes": []},
        )


class _Assets:
    def fetch_bgm(self, style: str, output_dir: Path) -> None:
        return None


def test_orchestrator_persists_quiz_questions_and_community_draft(
    tmp_path: Path,
) -> None:
    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        gemini_api_key="test",
    )
    orchestrator = VideoPipelineOrchestrator(
        settings=settings,
        script_engine=_QuizScriptEngine(),  # type: ignore[arg-type]
        audio_engine=_AudioEngine(),  # type: ignore[arg-type]
        asset_service=_Assets(),  # type: ignore[arg-type]
    )

    result = orchestrator.run(
        PipelineRequest(
            idea="Greek gods quiz",
            format=VideoFormat.QUIZVERSE,
            quiz_mode=QuizMode.COMMENT,
            question_count=1,
            output_name="quiz-job",
        )
    )

    run_dir = Path(result.metadata["run_dir"])
    assert json.loads((run_dir / "quiz_questions.json").read_text(encoding="utf-8")) == QUESTIONS
    draft = (run_dir / "community_post_draft.txt").read_text(encoding="utf-8")
    assert "Greek Gods Quiz" in draft
    assert "Answer: Zeus" in draft


def test_workspace_exposes_quiz_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "quiz"
    run_dir.mkdir()
    (run_dir / "request.json").write_text(
        json.dumps({"idea": "Greek gods", "format": "quizverse", "quiz_mode": "comment"}),
        encoding="utf-8",
    )
    (run_dir / "quiz_questions.json").write_text(json.dumps(QUESTIONS), encoding="utf-8")
    (run_dir / "community_post_draft.txt").write_text("Draft copy", encoding="utf-8")

    status = workspace_status(run_dir)

    assert status["format"] == "quizverse"
    assert status["quiz_mode"] == "comment"
    assert status["quiz_answer_key"] == QUESTIONS
    assert status["community_post_draft"] == "Draft copy"


def test_workspace_reconstructs_answer_key_from_script_scenes(tmp_path: Path) -> None:
    run_dir = tmp_path / "legacy-quiz"
    run_dir.mkdir()
    script = _QuizScriptEngine().generate(
        PipelineRequest(idea="Greek gods", format=VideoFormat.QUIZVERSE)
    )
    payload = script.model_dump(mode="json")
    payload.pop("questions_raw")
    (run_dir / "script.json").write_text(json.dumps(payload), encoding="utf-8")

    status = workspace_status(run_dir)

    assert status["format"] == "quizverse"
    assert status["quiz_mode"] == "comment"
    assert status["quiz_answer_key"] == QUESTIONS
