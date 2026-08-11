# YouTube SEO Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a unique, mode-aware YouTube SEO pack (titles, description, tags, hashtags, pinned comment, chapters) per job after Phase 1 script/TTS.

**Architecture:** New `youtube_pipeline/seo/` module produces `youtube_metadata.json` via one LLM call (soft-fail to story-specific fallback). Orchestrator runs it after TTS. Workspace + regenerate API expose the pack; Studio `YouTubeReachGuide` copies server fields instead of a static template.

**Tech Stack:** Python/Pydantic, existing ScriptEngine LLM call pattern, FastAPI, React Studio panel.

## Global Constraints

- Soft-fail: never block Phase 1 if packaging fails
- Shorts mode when aspect `9:16`; else longform
- Bilingual: script language + English keywords
- Full pack fields per spec `2026-08-09-youtube-seo-pack-design.md`
- Work in `.worktrees/dialogue-format`

---

### Task 1: SEO models + store + fallback

**Files:**
- Create: `src/youtube_pipeline/seo/__init__.py`
- Create: `src/youtube_pipeline/seo/models.py`
- Create: `src/youtube_pipeline/seo/store.py`
- Create: `src/youtube_pipeline/seo/fallback.py`
- Test: `tests/test_youtube_seo_pack.py`

- [ ] Write failing tests for mode selection, title clamp, fallback uniqueness
- [ ] Implement models/store/fallback
- [ ] Pass tests

### Task 2: LLM generator + prompts

**Files:**
- Create: `src/youtube_pipeline/seo/prompts.py`
- Create: `src/youtube_pipeline/seo/generator.py`
- Modify: tests

- [ ] Tests for LLM JSON parse + paid/soft-fail path using mock llm_call
- [ ] Implement `generate_youtube_pack(script, request, *, timed_script=None, llm_call=None)`
- [ ] Pass tests

### Task 3: Orchestrator + regen-script hook

**Files:**
- Modify: `src/youtube_pipeline/orchestrator.py`
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py` (regen script path if needed)

- [ ] After TTS/timing, call generate + save (try/except log)
- [ ] After quality regen-script + TTS, regenerate pack
- [ ] Test with mocked generator

### Task 4: API + workspace

**Files:**
- Modify: `src/youtube_pipeline/api/main.py`
- Modify: `src/youtube_pipeline/api/schemas.py`
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py`
- Test: `tests/test_youtube_seo_api.py`

- [ ] Expose `youtube_pack` on workspace
- [ ] `POST .../youtube-pack/regenerate`
- [ ] Pass API tests

### Task 5: Frontend pack UI

**Files:**
- Copy/adapt: `frontend/src/components/YouTubeReachGuide.tsx`
- Copy/adapt: `frontend/src/lib/youtubeReachProgress.ts`
- Modify: `frontend/src/api/client.ts`, `types.ts`, `JobStudio.tsx`

- [ ] Prefer server pack fields for copy buttons
- [ ] Regenerate pack button
- [ ] Remove static identical template when pack present
