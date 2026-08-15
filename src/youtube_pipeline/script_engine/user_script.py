"""Ingest creator-provided scripts (plain text or JSON) into VideoScript."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from youtube_pipeline.audio.sfx_tags import apply_sfx_fallback
from youtube_pipeline.dialogue import assign_voices, expand_dialogue_script
from youtube_pipeline.exceptions import ScriptGenerationError
from youtube_pipeline.models import (
    PipelineRequest,
    QuizMode,
    SceneData,
    VideoFormat,
    VideoScript,
)
from youtube_pipeline.quiz.beats import assert_no_answer_leak, expand_quiz_questions
from youtube_pipeline.script_engine.prompts import (
    build_visual_style_anchor,
    ensure_visual_prompt_has_anchor,
)
from youtube_pipeline.script_engine.schema import (
    validate_dialogue_script_payload,
    validate_quiz_script_payload,
)
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_DIALOGUE_LINE_RE = re.compile(r"^([^:]{1,40}):\s*(.+)$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
LlmCall = Callable[..., str]


def _active_tts_provider():
    from config.settings import TTSProvider, get_settings

    try:
        return get_settings().tts_provider
    except Exception:  # noqa: BLE001
        return TTSProvider.EDGE_TTS


def ingest_user_script(
    request: PipelineRequest,
    *,
    llm_call: LlmCall | None = None,
    enrich: bool = True,
) -> VideoScript:
    """Parse a provided script and optionally enrich visuals via LLM.

    Free-form creative briefs (markdown, timings, speakers, visual plans) are
    structured by the LLM with format auto-detection. Rigid parsers are the
    fallback when the LLM is unavailable or fails.
    """
    if request.script_source != "provided":
        raise ScriptGenerationError("ingest_user_script requires script_source=provided")

    used_freeform = False
    if request.user_script_json is not None:
        script = _from_json(request.user_script_json, request)
    else:
        text = (request.user_script_text or "").strip()
        if not text:
            raise ScriptGenerationError("user_script_text is empty")
        if llm_call is not None:
            try:
                script = _from_freeform_llm(text, request, llm_call=llm_call)
                used_freeform = True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Freeform script ingest failed; falling back to rigid parsers | %s",
                    exc,
                )
                script = _from_rigid_text(text, request)
        else:
            script = _from_rigid_text(text, request)

    if enrich and not used_freeform:
        script = enrich_visuals(script, request, llm_call=llm_call)
    elif enrich and used_freeform and _needs_visual_enrich(script):
        script = enrich_visuals(script, request, llm_call=llm_call)
    return script


def _from_rigid_text(text: str, request: PipelineRequest) -> VideoScript:
    """Parse provided text with rigid rules, auto-correcting mismatched format hints."""
    if request.format == VideoFormat.QUIZVERSE:
        return _from_quiz_text(text, request)

    # Cinematic briefs with sparse "Name: line" quotes are narrative, not dialogue.
    # Only use the Name:text parser when the brief is mostly spoken dialogue lines.
    if request.format == VideoFormat.DIALOGUE and _looks_like_dialogue_script(text):
        return _from_dialogue_text(text, request)
    if request.format == VideoFormat.DIALOGUE:
        logger.warning(
            "Format=dialogue but brief is not mostly 'Name: text' lines; "
            "using narrative parser for cinematic/structure briefs"
        )
    return _from_narrative_text(text, request)


def _is_plausible_speaker_name(name: str) -> bool:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 40:
        return False
    # Timecode fragments like "0" / "10" from "0:00–0:30 — The Hook".
    if cleaned.isdigit():
        return False
    words = cleaned.replace("-", " ").split()
    if len(words) > 4:
        return False
    if any(marker in cleaned for marker in ("—", "–", "|", "/", "•")):
        return False
    # Titles / section labels often use Title Case phrases without being speakers.
    lowered = cleaned.casefold()
    if lowered.startswith(
        (
            "format",
            "length",
            "narration",
            "opening",
            "story",
            "end card",
            "visual",
            "section",
            "chapter",
            "scene",
        )
    ):
        return False
    return True


def _looks_like_dialogue_script(text: str) -> bool:
    """True when enough non-empty lines are short ``Name: spoken text`` cues."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    hits = 0
    for line in lines:
        # Timestamp / section headers are never dialogue turns.
        if re.match(r"^\d{1,2}:\d{2}\b", line):
            continue
        match = _DIALOGUE_LINE_RE.match(line)
        if not match:
            continue
        if _is_plausible_speaker_name(match.group(1)):
            hits += 1
    # Require a solid majority so film treatments don't trip dialogue mode.
    return hits >= 2 and (hits / len(lines)) >= 0.4


def _needs_visual_enrich(script: VideoScript) -> bool:
    if not script.scenes:
        return True
    weak = 0
    for scene in script.scenes:
        prompt = (scene.visual_prompt or "").strip()
        if not prompt or prompt.lower().startswith("cinematic shot:"):
            weak += 1
    return weak > max(1, len(script.scenes) // 2)


_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _from_freeform_llm(
    text: str,
    request: PipelineRequest,
    *,
    llm_call: LlmCall,
) -> VideoScript:
    """LLM-structure an arbitrary creative brief into a VideoScript."""
    system_prompt = (
        "You convert creator video briefs into strict JSON for a video pipeline. "
        "Auto-detect format:\n"
        "- narrative: DEFAULT for cinematic film treatments, timed story structures, "
        "documentaries, and scripts where a narrator carries most of the VO "
        "(even if a few quoted character lines appear)\n"
        "- dialogue: ONLY if the brief is primarily multi-speaker conversation "
        "(most lines are spoken turns by named roles; Narrator counts; "
        "pad cast to 3–4 with unused Guest roles if needed)\n"
        "- quizverse: if the brief is primarily Q/A trivia\n"
        "Keep spoken dialogue/narration faithful — do not paraphrase VO lines. "
        "Use Visual Plan / shot list items for visual_prompt when present. "
        "Omit markdown headings, length notes, and production notes from spoken text. "
        "Return JSON only."
    )
    user_prompt = (
        f"Creator idea/context: {request.idea}\n"
        f"Form format hint (may override via auto-detect): {request.format.value}\n"
        f"Form style hint: {request.style.value}\n"
        f"Form duration hint seconds: {request.target_duration_seconds}\n"
        f"Language: {request.language or 'en'}\n\n"
        "Return JSON with keys:\n"
        '- format: "narrative" | "dialogue" | "quizverse"\n'
        "- title: string\n"
        "- style: string (optional)\n"
        "- target_duration_seconds: number (optional)\n"
        "- For narrative: scenes: [{script_text, visual_prompt}]\n"
        "- For dialogue: cast: [{id, name, gender_hint}], "
        "lines: [{speaker_id, text, visual_prompt?}]\n"
        "- For quizverse: quiz_mode: \"comment\"|\"reveal\", "
        "questions: [{question, answer, choices?, explain?}]\n\n"
        f"CREATOR BRIEF:\n{text}"
    )
    raw = llm_call(user_prompt, system_prompt=system_prompt)
    payload = _parse_llm_json(raw)
    return _video_script_from_structured(payload, request)


def _parse_llm_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(raw or "")
        if not match:
            raise ScriptGenerationError("Freeform ingest LLM did not return JSON")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ScriptGenerationError("Freeform ingest JSON root must be an object")
    return data


def _video_script_from_structured(
    payload: dict[str, Any],
    request: PipelineRequest,
) -> VideoScript:
    fmt_raw = str(payload.get("format") or request.format.value).strip().lower()
    if fmt_raw not in {
        VideoFormat.NARRATIVE.value,
        VideoFormat.DIALOGUE.value,
        VideoFormat.QUIZVERSE.value,
    }:
        # Auto-pick from content shape
        if payload.get("questions"):
            fmt_raw = VideoFormat.QUIZVERSE.value
        elif payload.get("cast") and payload.get("lines"):
            fmt_raw = VideoFormat.DIALOGUE.value
        else:
            fmt_raw = VideoFormat.NARRATIVE.value

    title = str(payload.get("title") or request.idea or "Untitled").strip()[:80] or "Untitled"
    style = str(payload.get("style") or request.style.value).strip().lower() or request.style.value

    if fmt_raw == VideoFormat.DIALOGUE.value:
        cast = list(payload.get("cast") or [])
        lines = list(payload.get("lines") or [])
        if not lines:
            raise ScriptGenerationError("Freeform dialogue payload missing lines")
        cast = _normalize_dialogue_cast(cast, lines)
        scenes, enriched_lines = expand_dialogue_script(
            cast=cast,
            lines=lines,
            visual_beats=payload.get("visual_beats"),
            language=request.language or "en",
        )
        voice_map = assign_voices(
            cast,
            language=request.language or "en",
            provider=_active_tts_provider(),
        )
        return VideoScript(
            title=title,
            full_script=" ".join(line["text"] for line in enriched_lines),
            style=style,
            format=VideoFormat.DIALOGUE.value,
            cast=cast,
            lines=enriched_lines,
            voice_map=voice_map,
            scenes=scenes,
        )

    if fmt_raw == VideoFormat.QUIZVERSE.value:
        questions = list(payload.get("questions") or [])
        if not questions:
            raise ScriptGenerationError("Freeform quiz payload missing questions")
        mode_raw = str(payload.get("quiz_mode") or (request.quiz_mode or QuizMode.COMMENT).value)
        mode = QuizMode(mode_raw) if mode_raw in {m.value for m in QuizMode} else (
            request.quiz_mode or QuizMode.COMMENT
        )
        scenes = expand_quiz_questions(
            questions,
            mode=mode,
            language=request.language or "en",
            target_scene_count=int(request.max_scenes),
        )
        if mode == QuizMode.COMMENT:
            assert_no_answer_leak(scenes, questions)
        return VideoScript(
            title=title,
            full_script=" ".join(
                scene.script_text for scene in scenes if scene.script_text.strip()
            ),
            style=style,
            format=VideoFormat.QUIZVERSE.value,
            quiz_mode=mode.value,
            questions_raw=questions,
            scenes=scenes,
        )

    # Narrative
    scenes_raw = list(payload.get("scenes") or [])
    if not scenes_raw:
        raise ScriptGenerationError("Freeform narrative payload missing scenes")
    style_anchor = build_visual_style_anchor(idea=request.idea or title, style=request.style)
    scenes: list[SceneData] = []
    for index, item in enumerate(scenes_raw):
        if not isinstance(item, dict):
            raise ScriptGenerationError(f"scenes[{index}] must be an object")
        script_text = str(
            item.get("script_text") or item.get("narration") or item.get("text") or ""
        ).strip()
        if not script_text:
            raise ScriptGenerationError(f"scenes[{index}] missing spoken text")
        scenes.append(
            apply_sfx_fallback(
                SceneData(
                    scene_id=index,
                    script_text=script_text,
                    visual_prompt=ensure_visual_prompt_has_anchor(
                        str(item.get("visual_prompt") or f"Cinematic shot: {script_text}"),
                        style_anchor,
                    ),
                )
            )
        )
    return VideoScript(
        title=title,
        full_script=" ".join(scene.script_text for scene in scenes),
        style=style,
        format=VideoFormat.NARRATIVE.value,
        scenes=scenes,
    )


def _normalize_dialogue_cast(
    cast: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure 3–4 cast members with ids referenced by lines."""
    by_id: dict[str, dict[str, Any]] = {}
    for member in cast:
        if not isinstance(member, dict):
            continue
        mid = str(member.get("id") or "").strip()
        name = str(member.get("name") or mid).strip()
        if not mid:
            continue
        by_id[mid] = {
            "id": mid,
            "name": name or mid,
            "gender_hint": str(member.get("gender_hint") or ""),
        }

    # Discover speakers from lines
    for line in lines:
        sid = str(line.get("speaker_id") or "").strip()
        if sid and sid not in by_id:
            by_id[sid] = {"id": sid, "name": sid, "gender_hint": ""}

    members = list(by_id.values())
    if not members:
        raise ScriptGenerationError("Freeform dialogue has no cast/speakers")
    if len(members) > 4:
        # Keep speakers that appear in lines first
        used = {
            str(line.get("speaker_id") or "").strip()
            for line in lines
            if str(line.get("speaker_id") or "").strip()
        }
        ordered = [m for m in members if m["id"] in used] + [
            m for m in members if m["id"] not in used
        ]
        members = ordered[:4]
        keep = {m["id"] for m in members}
        for line in lines:
            if str(line.get("speaker_id") or "").strip() not in keep:
                line["speaker_id"] = members[0]["id"]
    while len(members) < 3:
        guest_id = f"guest{len(members) + 1}"
        members.append({"id": guest_id, "name": f"Guest{len(members) + 1}", "gender_hint": ""})
    return members


def enrich_visuals(
    script: VideoScript,
    request: PipelineRequest,
    *,
    llm_call: LlmCall | None = None,
) -> VideoScript:
    """Fill missing title/visual prompts without changing spoken words."""
    spoken_before = _spoken_fingerprint(script)
    style_anchor = build_visual_style_anchor(idea=request.idea, style=request.style)

    if llm_call is None:
        scenes = [
            scene.model_copy(
                update={
                    "visual_prompt": ensure_visual_prompt_has_anchor(
                        scene.visual_prompt or f"Cinematic shot: {scene.script_text}",
                        style_anchor,
                    )
                }
            )
            for scene in script.scenes
        ]
        enriched = script.model_copy(update={"scenes": scenes})
        if _spoken_fingerprint(enriched) != spoken_before:
            raise ScriptGenerationError("Visual enrich mutated spoken script text")
        return enriched

    scene_payload = [
        {
            "scene_id": scene.scene_id,
            "script_text": scene.script_text,
            "visual_prompt": scene.visual_prompt,
        }
        for scene in script.scenes
    ]
    system_prompt = (
        "You enrich video scene visuals. Return JSON only with keys "
        "`title` (string) and `scenes` (array of {scene_id, visual_prompt}). "
        "Do not change or rewrite narration. Visual prompts must be cinematic, "
        "text-free image descriptions matching the style."
    )
    user_prompt = (
        f"Idea/context: {request.idea}\n"
        f"Style: {request.style.value}\n"
        f"Format: {script.format}\n"
        f"Current title: {script.title}\n"
        f"Scenes JSON: {json.dumps(scene_payload, ensure_ascii=False)}"
    )
    try:
        raw = llm_call(user_prompt, system_prompt=system_prompt)
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            raise ValueError("enrich response must be an object")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Visual enrich LLM failed; using placeholders | %s", exc)
        return enrich_visuals(script, request, llm_call=None)

    title = str(data.get("title") or script.title).strip() or script.title
    by_id = {
        int(item["scene_id"]): str(item.get("visual_prompt") or "").strip()
        for item in (data.get("scenes") or [])
        if isinstance(item, dict) and "scene_id" in item
    }
    scenes: list[SceneData] = []
    for scene in script.scenes:
        prompt = by_id.get(scene.scene_id) or scene.visual_prompt
        scenes.append(
            scene.model_copy(
                update={
                    "visual_prompt": ensure_visual_prompt_has_anchor(
                        prompt or f"Cinematic shot: {scene.script_text}",
                        style_anchor,
                    )
                }
            )
        )
    enriched = script.model_copy(update={"title": title, "scenes": scenes})
    if _spoken_fingerprint(enriched) != spoken_before:
        raise ScriptGenerationError("Visual enrich mutated spoken script text")
    return enriched


def _spoken_fingerprint(script: VideoScript) -> tuple[Any, ...]:
    return (
        tuple(scene.script_text for scene in script.scenes),
        tuple(
            (str(line.get("text") or ""), str(line.get("speaker_id") or ""))
            for line in script.lines
        ),
        json.dumps(script.questions_raw, sort_keys=True, ensure_ascii=False),
    )


def _from_narrative_text(text: str, request: PipelineRequest) -> VideoScript:
    beats = _split_narrative_beats(text, max_scenes=int(request.max_scenes))
    style_anchor = build_visual_style_anchor(idea=request.idea, style=request.style)
    scenes = [
        apply_sfx_fallback(
            SceneData(
                scene_id=index,
                script_text=beat,
                visual_prompt=ensure_visual_prompt_has_anchor(
                    f"Cinematic shot: {beat}",
                    style_anchor,
                ),
            )
        )
        for index, beat in enumerate(beats)
    ]
    full_script = " ".join(beat for beat in beats)
    title = (request.idea or beats[0])[:80].strip() or "Untitled"
    return VideoScript(
        title=title,
        full_script=full_script,
        style=request.style.value,
        format=VideoFormat.NARRATIVE.value,
        scenes=scenes,
    )


def _split_narrative_beats(text: str, *, max_scenes: int) -> list[str]:
    blocks = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if len(blocks) >= 2:
        if len(blocks) > max_scenes:
            return _pack_texts(blocks, max_scenes)
        return blocks

    sentences = [part.strip() for part in _SENTENCE_RE.split(text.strip()) if part.strip()]
    if not sentences:
        raise ScriptGenerationError("Narrative script is empty")
    if len(sentences) == 1:
        return sentences
    return _pack_texts(sentences, max(2, min(max_scenes, len(sentences))))


def _pack_texts(parts: list[str], buckets: int) -> list[str]:
    if buckets <= 1:
        return [" ".join(parts).strip()]
    if len(parts) <= buckets:
        return parts
    size = max(1, (len(parts) + buckets - 1) // buckets)
    packed: list[str] = []
    for index in range(0, len(parts), size):
        chunk = " ".join(parts[index : index + size]).strip()
        if chunk:
            packed.append(chunk)
        if len(packed) >= buckets:
            if index + size < len(parts):
                packed[-1] = (packed[-1] + " " + " ".join(parts[index + size :])).strip()
            break
    return packed or [" ".join(parts).strip()]


def _from_dialogue_text(text: str, request: PipelineRequest) -> VideoScript:
    parsed_lines: list[tuple[str, str]] = []
    skipped = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _DIALOGUE_LINE_RE.match(line)
        if not match or not _is_plausible_speaker_name(match.group(1)):
            skipped += 1
            continue
        parsed_lines.append((match.group(1).strip(), match.group(2).strip()))
    if len(parsed_lines) < 2:
        raise ScriptGenerationError(
            "Dialogue script needs at least 2 'Name: text' spoken lines. "
            "For cinematic film briefs, choose Narrative format or Use my script "
            "without Dialogue selected."
        )
    if skipped:
        logger.info(
            "Skipped %d non-dialogue lines while parsing Name:text script",
            skipped,
        )

    names: list[str] = []
    for name, _ in parsed_lines:
        if name not in names:
            names.append(name)
    if len(names) > 4:
        raise ScriptGenerationError(
            f"Dialogue supports 3–4 speakers; found {len(names)}: {', '.join(names)}"
        )
    while len(names) < 3:
        names.append(f"Guest{len(names) + 1}")

    cast = [
        {"id": f"c{index}", "name": name, "gender_hint": ""}
        for index, name in enumerate(names)
    ]
    name_to_id = {member["name"]: member["id"] for member in cast}
    lines = [
        {
            "speaker_id": name_to_id[name],
            "text": spoken,
            "visual_prompt": f"Cinematic shot of {name} speaking: {spoken}",
        }
        for name, spoken in parsed_lines
    ]
    scenes, enriched_lines = expand_dialogue_script(
        cast=cast,
        lines=lines,
        visual_beats=None,
        language=request.language or "en",
    )
    voice_map = assign_voices(
        cast,
        language=request.language or "en",
        provider=_active_tts_provider(),
    )
    full_script = " ".join(line["text"] for line in enriched_lines)
    title = (request.idea or f"{names[0]} & {names[1]}")[:80].strip()
    return VideoScript(
        title=title,
        full_script=full_script,
        style=request.style.value,
        format=VideoFormat.DIALOGUE.value,
        cast=cast,
        lines=enriched_lines,
        voice_map=voice_map,
        scenes=scenes,
    )


def _from_quiz_text(text: str, request: PipelineRequest) -> VideoScript:
    questions = _parse_quiz_blocks(text)
    if not questions:
        raise ScriptGenerationError(
            "Quiz script needs blocks like 'Q: …' / 'A: …' (optional Choices/Explain)"
        )
    mode = request.quiz_mode or QuizMode.COMMENT
    maximum = 5 if mode == QuizMode.COMMENT else 15
    if len(questions) > maximum:
        raise ScriptGenerationError(
            f"{mode.value} mode supports at most {maximum} questions; got {len(questions)}"
        )
    title = (request.idea or questions[0]["question"])[:80].strip() or "Quiz"
    scenes = expand_quiz_questions(
        questions,
        mode=mode,
        language=request.language or "en",
        target_scene_count=int(request.max_scenes),
    )
    if mode == QuizMode.COMMENT:
        assert_no_answer_leak(scenes, questions)
    full_script = " ".join(
        scene.script_text for scene in scenes if scene.script_text.strip()
    )
    return VideoScript(
        title=title,
        full_script=full_script,
        style=request.style.value,
        format=VideoFormat.QUIZVERSE.value,
        quiz_mode=mode.value,
        questions_raw=questions,
        scenes=scenes,
    )


def _parse_quiz_blocks(text: str) -> list[dict[str, Any]]:
    blocks = [part.strip() for part in re.split(r"\n\s*\n+", text.strip()) if part.strip()]
    questions: list[dict[str, Any]] = []
    for block in blocks:
        fields: dict[str, str] = {}
        current_key: str | None = None
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            key_match = re.match(
                r"^(Q|Question|A|Answer|Choices|Options|Explain|Explanation)\s*:\s*(.*)$",
                line,
                flags=re.IGNORECASE,
            )
            if key_match:
                label = key_match.group(1).lower()
                if label in {"q", "question"}:
                    current_key = "question"
                elif label in {"a", "answer"}:
                    current_key = "answer"
                elif label in {"choices", "options"}:
                    current_key = "choices"
                else:
                    current_key = "explain"
                fields[current_key] = key_match.group(2).strip()
            elif current_key:
                fields[current_key] = (fields.get(current_key, "") + " " + line).strip()
        question = (fields.get("question") or "").strip()
        answer = (fields.get("answer") or "").strip()
        if not question or not answer:
            # Allow a single freeform block as one question if it starts with Q:
            continue
        choices_raw = (fields.get("choices") or "").strip()
        choices = [
            part.strip()
            for part in re.split(r"\s*\|\s*", choices_raw)
            if part.strip()
        ] if choices_raw else []
        questions.append(
            {
                "question": question,
                "answer": answer,
                "choices": choices,
                "explain": (fields.get("explain") or "").strip(),
            }
        )
    return questions


def _from_json(payload: dict[str, Any], request: PipelineRequest) -> VideoScript:
    # Full VideoScript dump
    if "scenes" in payload and "full_script" in payload:
        script = VideoScript.model_validate(
            {
                **payload,
                "style": payload.get("style") or request.style.value,
                "format": payload.get("format") or request.format.value,
            }
        )
        return script

    if request.format == VideoFormat.DIALOGUE or (
        "cast" in payload and "lines" in payload
    ):
        # Soft validation: skip rigid 8–16 line generator constraint for BYOS.
        cast = payload.get("cast") or []
        lines = payload.get("lines") or []
        if not cast or not lines:
            raise ScriptGenerationError("Dialogue JSON needs cast and lines")
        if len(cast) not in {3, 4}:
            raise ScriptGenerationError("Dialogue JSON cast must have 3 or 4 members")
        # Prefer validate when line count fits generator schema; else expand directly.
        try:
            validated = validate_dialogue_script_payload(payload)
            cast = validated["cast"]
            lines = validated["lines"]
            visual_beats = validated.get("visual_beats")
        except Exception:
            visual_beats = payload.get("visual_beats")
        scenes, enriched_lines = expand_dialogue_script(
            cast=cast,
            lines=lines,
            visual_beats=visual_beats,
            language=request.language or "en",
        )
        voice_map = assign_voices(
            cast,
            language=request.language or "en",
            provider=_active_tts_provider(),
        )
        title = str(payload.get("title") or request.idea or "Dialogue")[:80]
        return VideoScript(
            title=title,
            full_script=" ".join(line["text"] for line in enriched_lines),
            style=request.style.value,
            format=VideoFormat.DIALOGUE.value,
            cast=cast,
            lines=enriched_lines,
            voice_map=voice_map,
            scenes=scenes,
        )

    if request.format == VideoFormat.QUIZVERSE or "questions" in payload:
        mode = request.quiz_mode or QuizMode.COMMENT
        questions = payload.get("questions") or []
        if not questions:
            raise ScriptGenerationError("Quiz JSON needs a questions array")
        try:
            validated = validate_quiz_script_payload(
                payload,
                question_count=len(questions),
            )
            questions = validated["questions"]
            title = validated["title"]
        except Exception:
            title = str(payload.get("title") or request.idea or "Quiz")
        scenes = expand_quiz_questions(
            questions,
            mode=mode,
            language=request.language or "en",
            target_scene_count=int(request.max_scenes),
        )
        if mode == QuizMode.COMMENT:
            assert_no_answer_leak(scenes, questions)
        return VideoScript(
            title=str(title)[:80],
            full_script=" ".join(
                scene.script_text for scene in scenes if scene.script_text.strip()
            ),
            style=request.style.value,
            format=VideoFormat.QUIZVERSE.value,
            quiz_mode=mode.value,
            questions_raw=questions,
            scenes=scenes,
        )

    # Narrative-like {title, scenes:[{script_text|narration, visual_prompt}]}
    scenes_raw = payload.get("scenes") or []
    if not scenes_raw:
        raise ScriptGenerationError("JSON script must include scenes or format payload")
    style_anchor = build_visual_style_anchor(idea=request.idea, style=request.style)
    scenes: list[SceneData] = []
    for index, item in enumerate(scenes_raw):
        if not isinstance(item, dict):
            raise ScriptGenerationError(f"scenes[{index}] must be an object")
        script_text = str(
            item.get("narration")
            or item.get("script_text")
            or item.get("text")
            or ""
        ).strip()
        if not script_text:
            raise ScriptGenerationError(f"scenes[{index}] missing narration text")
        scenes.append(
            apply_sfx_fallback(
                SceneData(
                    scene_id=int(item.get("scene_id", index)),
                    script_text=script_text,
                    visual_prompt=ensure_visual_prompt_has_anchor(
                        str(item.get("visual_prompt") or f"Cinematic shot: {script_text}"),
                        style_anchor,
                    ),
                    keywords=list(item.get("keywords") or []),
                    ambience=item.get("ambience", "none"),
                    sfx=item.get("sfx", []),
                )
            )
        )
    scenes = [scene.model_copy(update={"scene_id": idx}) for idx, scene in enumerate(scenes)]
    title = str(payload.get("title") or request.idea or scenes[0].script_text)[:80]
    full_script = str(
        payload.get("full_script") or " ".join(scene.script_text for scene in scenes)
    ).strip()
    return VideoScript(
        title=title.strip() or "Untitled",
        full_script=full_script,
        style=str(payload.get("style") or request.style.value).strip().lower(),
        format=VideoFormat.NARRATIVE.value,
        scenes=scenes,
    )
