"""Generate YouTube SEO packs via LLM with story-specific fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from youtube_pipeline.models import PipelineRequest, VideoScript
from youtube_pipeline.seo.fallback import (
    build_fallback_pack,
    clamp_title,
    resolve_pack_mode,
)
from youtube_pipeline.seo.models import YoutubeChapter, YoutubePack
from youtube_pipeline.seo.prompts import build_seo_system_prompt, build_seo_user_prompt
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

LlmCall = Callable[..., str]

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Empty SEO LLM response")
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("SEO pack JSON must be an object")
    return payload


def _default_llm_call(user_prompt: str, *, system_prompt: str) -> str:
    from youtube_pipeline.script_engine.generator import ScriptEngine

    return ScriptEngine()._call_llm(user_prompt, system_prompt=system_prompt)


def _pack_from_llm_payload(
    payload: dict[str, Any],
    *,
    script: VideoScript,
    request: PipelineRequest,
    timed_script: VideoScript | None,
) -> YoutubePack:
    mode = resolve_pack_mode(request.aspect_ratio)
    language = (request.language or "en").strip() or "en"
    primary = clamp_title(
        str(payload.get("primary_title") or script.title or request.idea or "Untitled"),
        mode=mode,
    )
    alts_raw = payload.get("alt_titles") or []
    if not isinstance(alts_raw, list):
        alts_raw = []
    alt_titles = [
        clamp_title(str(item), mode=mode)
        for item in alts_raw
        if str(item).strip()
    ][:3]

    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("SEO pack missing description")

    tags = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()][:20]
    hashtags = list(payload.get("hashtags") or [])
    if mode == "shorts" and not any(str(h).lower().replace("#", "") == "shorts" for h in hashtags):
        hashtags = ["#shorts", *hashtags]

    chapters_payload = payload.get("chapters") or []
    chapters: list[YoutubeChapter] = []
    if mode != "shorts" and isinstance(chapters_payload, list):
        for item in chapters_payload[:8]:
            if not isinstance(item, dict):
                continue
            try:
                chapters.append(
                    YoutubeChapter(
                        start_seconds=int(item.get("start_seconds") or 0),
                        label=str(item.get("label") or "Beat")[:80],
                    )
                )
            except Exception:  # noqa: BLE001
                continue
    if mode != "shorts" and not chapters and timed_script is not None:
        chapters = build_fallback_pack(
            script, request, timed_script=timed_script
        ).chapters

    return YoutubePack(
        mode=mode,  # type: ignore[arg-type]
        language=language,
        primary_title=primary,
        alt_titles=alt_titles,
        description=description[:5000],
        tags=tags,
        hashtags=hashtags,
        pinned_comment=str(payload.get("pinned_comment") or "")[:500],
        chapters=chapters,
        source="llm",
    )


def generate_youtube_pack(
    script: VideoScript,
    request: PipelineRequest,
    *,
    timed_script: VideoScript | None = None,
    llm_call: LlmCall | None = None,
) -> YoutubePack:
    """Build a YouTube SEO pack; soft-falls back to a story-specific template."""
    mode = resolve_pack_mode(request.aspect_ratio)
    language = (request.language or "en").strip() or "en"
    call = llm_call or _default_llm_call
    try:
        raw = call(
            build_seo_user_prompt(script, request, timed_script=timed_script),
            system_prompt=build_seo_system_prompt(mode=mode, language=language),
        )
        pack = _pack_from_llm_payload(
            _extract_json(raw),
            script=script,
            request=request,
            timed_script=timed_script,
        )
        logger.info(
            "YouTube SEO pack ready | source=llm | mode=%s | title=%r",
            pack.mode,
            pack.primary_title,
        )
        return pack
    except Exception as exc:  # noqa: BLE001
        logger.warning("YouTube SEO LLM pack failed (%s); using fallback", exc)
        pack = build_fallback_pack(script, request, timed_script=timed_script)
        logger.info(
            "YouTube SEO pack ready | source=fallback | mode=%s | title=%r",
            pack.mode,
            pack.primary_title,
        )
        return pack
