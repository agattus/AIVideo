"""Tests for project path bootstrapping (Windows uvicorn thread safety)."""

from __future__ import annotations

import sys
from pathlib import Path

from youtube_pipeline.utils.paths import ensure_project_paths


def test_ensure_project_paths_makes_config_importable() -> None:
    # Simulate a broken path like Windows uvicorn threads sometimes see.
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    removed: list[str] = []
    for entry in (str(repo_root), str(src_dir)):
        while entry in sys.path:
            sys.path.remove(entry)
            removed.append(entry)

    try:
        # May or may not already be importable via site-packages editable install.
        ensure_project_paths()
        assert str(repo_root) in sys.path
        assert str(src_dir) in sys.path
        import config.settings  # noqa: F401
        from config.settings import Settings  # noqa: F401

        assert Settings is not None
    finally:
        # Leave path usable for later tests.
        ensure_project_paths()


def test_execute_pipeline_marks_failed_when_orchestrator_import_breaks(
    monkeypatch,
) -> None:
    from youtube_pipeline.api import tasks as tasks_mod
    from youtube_pipeline.api.job_store import get_job, init_job
    from youtube_pipeline.api.schemas import JobStatus

    init_job("job-import-fail")

    def boom():
        raise ModuleNotFoundError("No module named 'config'")

    monkeypatch.setattr(tasks_mod, "ensure_project_paths", lambda: None)

    # Force the orchestrator import inside execute_video_pipeline to fail.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "youtube_pipeline.orchestrator" or (
            name == "youtube_pipeline" and fromlist and "orchestrator" in fromlist
        ):
            raise ModuleNotFoundError("No module named 'config'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    try:
        tasks_mod.execute_video_pipeline("job-import-fail", {"idea": "RAG in AI"})
        assert False, "expected ModuleNotFoundError"
    except ModuleNotFoundError:
        pass

    state = get_job("job-import-fail")
    assert state is not None
    assert state.status == JobStatus.FAILED
    assert state.error
    assert "config" in state.error
