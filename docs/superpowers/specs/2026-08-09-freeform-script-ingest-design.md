# Freeform Script Ingest — Design

**Date:** 2026-08-09  
**Status:** Approved  
**Branch:** `feat/dialogue-format`

## Goal

Creators paste any creative brief (markdown, timings, speakers, visual plans, quiz blocks, or plain prose). The pipeline **auto-detects format** and builds a `VideoScript` for narrative / dialogue / quizverse without requiring rigid paste syntax.

## Decisions

| Topic | Choice |
|-------|--------|
| Parser | LLM structure pass (Approach A) |
| Multi-speaker | Auto-pick: dialogue if ≥2 named speaking roles; else narrative/quiz |
| Words | Sacred — quality critique only, no rewrite (existing BYOS policy) |
| Form format | Soft default; detected format wins for provided scripts |
| Fallback | Existing rigid parsers if LLM unavailable/fails |

## Flow

1. Compose **Use my script** → `script_source=provided` + free-form text.
2. `ingest_user_script` calls LLM → structured JSON (`format`, title, spoken units, visuals).
3. Expand via existing dialogue/quiz helpers or narrative `SceneData` list.
4. Orchestrator syncs `request.format` to detected format; writes sidecars; TTS; quality (no rewrite).

## LLM output contract (summary)

- `format`: `narrative` \| `dialogue` \| `quizverse`
- `title`, optional `style`, `target_duration_seconds`
- Narrative: `scenes[{script_text, visual_prompt}]`
- Dialogue: `cast[3–4]`, `lines[{speaker_id, text, visual_prompt?}]`
- Quizverse: `quiz_mode`, `questions[{question, answer, choices?, explain?}]`
- Prefer Visual Plan bullets for `visual_prompt` when present in the paste
- Spoken text must stay faithful to the creator’s lines (no paraphrasing for VO)

## Non-goals

- Editing the freeform brief inside Studio after create
- Guaranteeing bit-identical wording if the LLM misbehaves (mitigate with fingerprint checks on dialogue lines / scene texts where practical)
