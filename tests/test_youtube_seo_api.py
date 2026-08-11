"""API coverage for YouTube SEO pack regenerate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from youtube_pipeline.api.main import app
from youtube_pipeline.api.schemas import JobStatus
from youtube_pipeline.models import PipelineRequest, VideoScript
from youtube_pipeline.seo import save_youtube_pack
from youtube_pipeline.seo.fallback import build_fallback_pack


def test_regenerate_youtube_pack_endpoint(tmp_path: Path, monkeypatch) -> None:
    job_id = "seo-pack-job"
    run_dir = tmp_path / job_id
    run_dir.mkdir()
    script = VideoScript(
        title="The Open Gate",
        full_script="The gate opens. Shadows move.",
        style="cinematic",
        scenes=[
            {
                "scene_id": 0,
                "script_text": "The gate opens.",
                "visual_prompt": "open gate",
                "duration": 3.0,
            }
        ],
    )

    def fake_regen(run_dir_arg, **kwargs):
        pack = build_fallback_pack(
            script,
            PipelineRequest(idea="Ancient fortress opens at midnight", style="cinematic"),
        )
        save_youtube_pack(run_dir_arg, pack)
        return pack

    job = SimpleNamespace(job_id=job_id, status=JobStatus.WAITING_FOR_ASSETS, run_dir=str(run_dir))
    monkeypatch.setattr("youtube_pipeline.api.main.regenerate_youtube_pack", fake_regen)
    monkeypatch.setattr("youtube_pipeline.api.main.publish_workspace_static", lambda *a, **k: None)
    monkeypatch.setattr(
        "youtube_pipeline.api.main._require_job_run_dir",
        lambda job_id_arg, mutate=True: (job, run_dir),
    )

    client = TestClient(app)
    res = client.post(f"/api/v1/jobs/{job_id}/youtube-pack/regenerate")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["job_id"] == job_id
    assert body["youtube_pack"]["primary_title"]
    assert body["youtube_pack"]["description"]
