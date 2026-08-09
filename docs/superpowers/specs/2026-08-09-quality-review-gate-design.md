# Quality review gate — Design

**Date:** 2026-08-09  
**Status:** Approved for planning  
**Goal:** Add a hybrid creative quality gate (script + timing + image aptness) across all formats, with one auto-retry then Studio checklist before Assemble.

## Problem

The pipeline validates structure (JSON schema, holds, file presence) and Studio lets humans swap images/voices, but nothing scores whether the **script fits the idea**, opens with a **hook**, **ends cleanly**, has **pace/emotion**, whether **VO/captions are sane**, or whether **images match their lines**. Weak films can assemble whenever assets exist.

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Failure handling | **Hybrid:** auto-retry once; if still weak → Studio checklist |
| Scope of checks | **Full gate:** script + timing + per-scene image aptness |
| Formats | **All:** narrative, quizverse, dialogue |
| Approach | Staged LLM critique + deterministic timing + Studio approve/override |

## Non-goals (v1)

- Watching/scoring the final muxed MP4 with a video model  
- Guaranteed perfect films (override always available)  
- Replacing HITL image upload / cast remap  
- Paid AI video generation  
- Multi-round rewrite loops beyond one auto-retry per stage  

## Stages

### 1. Script quality (after `script_engine.generate`, before TTS)

LLM returns JSON rubric scores 1–5:

- `idea_fit`  
- `hook` (cold open / first beat)  
- `ending` (complete, not mid-thought)  
- `pacing_emotion` (tension, beats, pause cues)  
- `format_rules` (dialogue lines, quiz grammar, narrative scene count)

**Fail** if any score &lt; 3.  
**On fail:** one rewrite using critique feedback → re-score.  
**Still fail:** continue; set `script_review.status = needs_approval`.

Optional: rewrite may inject pace marks (`…`, short beats) when pacing scored low.

### 2. Timing sanity (after TTS, deterministic)

No LLM. Checks:

- Total VO duration vs creator `target_duration_seconds` within ±35% (skip band if duration omitted)  
- No empty/zero scene durations  
- Dialogue: `len(scenes) == len(lines)`  
- Caption/word timeline covers ≈ full VO (no huge silent tail)

**Fail** → `timing_review.status = needs_approval` (soft continue; regen VO is a Studio action).

### 3. Image aptness (after autofill / before Assemble)

Per scene with an image:

- Prefer Gemini vision comparing image bytes to `visual_prompt` + narration excerpt  
- Fallback: LLM text check of prompt vs narration consistency if vision unavailable  
- Score 1–5; fail &lt; 3 → regenerate that scene once  
- Still fail → `image_review.status = needs_approval` listing scene ids  

### 4. Studio Quality panel + Assemble gate

JobStudio shows:

| Row | States |
|-----|--------|
| Script | pass / needs attention |
| Timing | pass / needs attention |
| Images | pass / needs attention |

Expandable issue list. Actions: **Approve & continue** (override), **Regen script**, **Regen weak images**.  
**Assemble** disabled until all `pass` **or** each failing row has an explicit override approval.

Persist `quality_review.json` in the job run dir:

```json
{
  "script_review": {"status": "pass|needs_approval|overridden", "scores": {}, "issues": [], "retries": 0},
  "timing_review": {"status": "...", "issues": []},
  "image_review": {"status": "...", "scenes": {}, "retries": {}},
  "approvals": {"script": false, "timing": false, "images": false}
}
```

## Pipeline hooks

1. `VideoPipelineOrchestrator.run` — script review after generate, before TTS  
2. After TTS — timing review; write into `quality_review.json`  
3. After autofill / on workspace load — image review (or on Assemble attempt)  
4. `assemble_video` / resume — require quality gate or overrides  
5. API: expose review on workspace; endpoints for approve / regen script / regen weak images  

## Success criteria

1. Weak hook/ending/idea-fit scripts trigger rewrite once or land in Studio as needs attention.  
2. Timing outliers flagged without blocking Phase 1 completion.  
3. Off-prompt images regen once; persistent fails listed in Studio.  
4. Assemble blocked until pass or override.  
5. Narrative / Quizverse / Dialogue all exercise the gate.  
6. Existing smoke tests still pass; new unit tests cover rubric parse, timing checks, assemble gate.

## Determinism note (product expectation)

- **Deterministic:** timing checks, assemble gate rules, file presence, hard-concat A/V timeline.  
- **Stochastic:** LLM script critique/rewrite, image generation, vision aptness scores — same idea can yield different scores/scripts/images across runs.  
- Gate **reduces** bad outputs shipping; it does **not** make creative generation bit-identical.
