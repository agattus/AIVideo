from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from config.settings import Settings
from youtube_pipeline.api import tasks
from youtube_pipeline.api.job_store import get_job, init_job, update_job
from youtube_pipeline.api.schemas import GenerateVideoRequest, JobStatus
from youtube_pipeline.assets.hitl_workspace import workspace_status
from youtube_pipeline.audio.tts import TTSResult
from youtube_pipeline.models import (
    AspectRatio,
    PipelineRequest,
    SceneData,
    VideoFormat,
    VideoScript,
)
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator


CAST = [
    {"id": "ravi", "name": "Ravi", "gender_hint": "male"},
    {"id": "maya", "name": "Maya", "gender_hint": "female"},
    {"id": "guard", "name": "Guard", "gender_hint": "male"},
]
VOICE_MAP = {
    "ravi": "en-US-GuyNeural",
    "maya": "en-US-AriaNeural",
    "guard": "en-US-ChristopherNeural",
}
LINES = [
    {"speaker_id": "ravi", "speaker_name": "Ravi", "text": "We leave."},
    {"speaker_id": "maya", "speaker_name": "Maya", "text": "Wait."},
    {"speaker_id": "guard", "speaker_name": "Guard", "text": "Go now."},
]


def _dialogue_script() -> VideoScript:
    return VideoScript(
        title="Gate",
        full_script="We leave. Wait. Go now.",
        style="cinematic",
        format="dialogue",
        cast=CAST,
        lines=LINES,
        voice_map=VOICE_MAP,
        scenes=[
            SceneData(
                scene_id=0,
                script_text="We leave. Wait. Go now.",
                visual_prompt="Three people at a guarded gate",
                line_start=0,
                line_end=2,
            )
        ],
    )


def test_generate_request_accepts_dialogue_without_duration() -> None:
    request = GenerateVideoRequest(idea="A tense gate debate", format="dialogue")
    pipeline_request = tasks._build_pipeline_request(
        "dialogue-job",
        request.model_dump(),
    )

    assert request.format == VideoFormat.DIALOGUE
    assert request.duration is None
    assert pipeline_request.format == VideoFormat.DIALOGUE
    assert request.aspect_ratio is None
    assert pipeline_request.aspect_ratio == AspectRatio.VERTICAL


def test_dialogue_pipeline_request_defaults_to_vertical() -> None:
    request = PipelineRequest(idea="A tense gate debate", format=VideoFormat.DIALOGUE)
    assert request.aspect_ratio == AspectRatio.VERTICAL


def test_narrative_omitted_aspect_stays_landscape() -> None:
    request = GenerateVideoRequest(idea="A calm river story", format="narrative")
    pipeline_request = tasks._build_pipeline_request(
        "narrative-job",
        request.model_dump(),
    )
    assert pipeline_request.aspect_ratio == AspectRatio.LANDSCAPE


class _DialogueScriptEngine:
    def generate(self, request: PipelineRequest) -> VideoScript:
        return _dialogue_script()


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
            duration_seconds=3.0,
            script=script,
            word_timestamps=[],
            timing={"total_duration": 3.0, "scenes": []},
        )


class _Assets:
    def fetch_bgm(self, style: str, output_dir: Path) -> None:
        return None


def test_orchestrator_persists_dialogue_sidecars(tmp_path: Path) -> None:
    orchestrator = VideoPipelineOrchestrator(
        settings=Settings(
            output_dir=tmp_path / "out",
            assets_cache_dir=tmp_path / "cache",
            gemini_api_key="test",
        ),
        script_engine=_DialogueScriptEngine(),  # type: ignore[arg-type]
        audio_engine=_AudioEngine(),  # type: ignore[arg-type]
        asset_service=_Assets(),  # type: ignore[arg-type]
    )

    result = orchestrator.run(
        PipelineRequest(
            idea="A tense gate debate",
            format=VideoFormat.DIALOGUE,
            output_name="dialogue-job",
        )
    )

    run_dir = Path(result.metadata["run_dir"])
    assert json.loads((run_dir / "cast.json").read_text(encoding="utf-8")) == CAST
    assert json.loads((run_dir / "voice_map.json").read_text(encoding="utf-8")) == VOICE_MAP
    assert json.loads((run_dir / "dialogue_lines.json").read_text(encoding="utf-8")) == LINES


def test_workspace_exposes_cast_with_assigned_voices(tmp_path: Path) -> None:
    run_dir = tmp_path / "dialogue"
    run_dir.mkdir()
    (run_dir / "request.json").write_text(
        json.dumps({"idea": "A tense gate debate", "format": "dialogue"}),
        encoding="utf-8",
    )
    (run_dir / "cast.json").write_text(json.dumps(CAST), encoding="utf-8")
    (run_dir / "voice_map.json").write_text(json.dumps(VOICE_MAP), encoding="utf-8")

    status = workspace_status(run_dir)

    assert status["format"] == "dialogue"
    assert status["cast"] == [
        {"id": "ravi", "name": "Ravi", "voice_id": "en-US-GuyNeural"},
        {"id": "maya", "name": "Maya", "voice_id": "en-US-AriaNeural"},
        {"id": "guard", "name": "Guard", "voice_id": "en-US-ChristopherNeural"},
    ]


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._store.get(key)


def test_cast_voice_endpoint_persists_map_and_optionally_regenerates(
    tmp_path: Path,
) -> None:
    from youtube_pipeline.api.main import app

    fake = _FakeRedis()
    job_id = "dialogue-api-job"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    script = _dialogue_script()
    for name in ("script.json", "script_timed.json"):
        (run_dir / name).write_text(
            json.dumps(script.model_dump(mode="json")),
            encoding="utf-8",
        )
    (run_dir / "cast.json").write_text(json.dumps(CAST), encoding="utf-8")
    (run_dir / "voice_map.json").write_text(json.dumps(VOICE_MAP), encoding="utf-8")
    init_job(job_id, client=fake)  # type: ignore[arg-type]
    update_job(
        job_id,
        status=JobStatus.WAITING_FOR_ASSETS,
        run_dir=str(run_dir),
        client=fake,  # type: ignore[arg-type]
    )
    updated = {**VOICE_MAP, "maya": "en-US-JennyNeural"}

    with (
        patch(
            "youtube_pipeline.api.main.get_job",
            side_effect=lambda jid: get_job(jid, client=fake),  # type: ignore[arg-type]
        ),
        patch("youtube_pipeline.api.main._dispatch_voiceover") as dispatch,
    ):
        response = TestClient(app).post(
            f"/api/v1/jobs/{job_id}/cast/voices",
            json={"voice_map": updated, "regenerate": True},
        )

    assert response.status_code == 202
    assert response.json()["cast"][1]["voice_id"] == "en-US-JennyNeural"
    assert json.loads((run_dir / "voice_map.json").read_text(encoding="utf-8")) == updated
    persisted = json.loads((run_dir / "script.json").read_text(encoding="utf-8"))
    assert persisted["voice_map"] == updated
    dispatch.assert_called_once_with(job_id, run_dir, "dialogue_cast")
