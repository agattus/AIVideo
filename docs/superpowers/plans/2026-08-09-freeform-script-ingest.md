# Freeform Script Ingest Implementation Plan

> **For agentic workers:** Implement task-by-task; keep spoken words faithful; auto-detect format.

**Goal:** LLM-parse arbitrary creative briefs into VideoScript with format auto-detection.

**Tech:** Existing `user_script.py`, orchestrator BYOS path, GenerateForm placeholders, pytest mocks.

## Task 1: Freeform LLM ingest + fallback

**Files:** `src/youtube_pipeline/script_engine/user_script.py`, `tests/test_freeform_script_ingest.py`

- Add `_from_freeform_llm(text, request, llm_call) -> VideoScript`
- Prefer LLM when `llm_call` present; on failure fall back to rigid parsers
- Auto-pick format from payload; pad dialogue cast to 3–4
- Skip visual enrich when prompts already present (or enrich only empties — already)

## Task 2: Orchestrator sync detected format

**Files:** `src/youtube_pipeline/orchestrator.py`

- After ingest, if `script.format` differs from `request.format`, update request + rewrite `request.json`

## Task 3: UI copy

**Files:** `frontend/src/components/GenerateForm.tsx`, rebuild `web/`

- Placeholder explains free-form briefs (markdown, speakers, visual plans OK)
- Note that format is auto-detected

## Task 4: Tests

- Mocked LLM → dialogue for multi-speaker Matsya-like paste
- Mocked LLM → narrative
- Fallback when LLM raises
