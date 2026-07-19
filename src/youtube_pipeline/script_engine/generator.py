"""LLM-backed script engine (Groq via OpenAI-compatible client + Pydantic parse)."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config.settings import LLMProvider, Settings, get_settings, mask_secret
from youtube_pipeline.exceptions import ConfigurationError, ScriptGenerationError
from youtube_pipeline.models import PipelineRequest, SceneData, VideoScript
from youtube_pipeline.script_engine.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    compute_min_scenes,
    compute_target_words,
)
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def _is_retryable_llm_error(exc: BaseException) -> bool:
    """Retry transient failures only — never retry bad API keys / auth."""
    if isinstance(exc, ConfigurationError):
        return False
    name = type(exc).__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return False
    text = str(exc).lower()
    if "invalid_api_key" in text or "invalid api key" in text:
        return False
    if "authentication" in text and "401" in text:
        return False
    return True


class ScriptEngine:
    """Generate a ``VideoScript`` from idea/style via Groq (OpenAI-compatible API).

    Uses the official ``openai`` Python package pointed at Groq's base URL, with
    ``response_format={"type": "json_object"}`` (natively supported by Groq).
    The JSON string is then validated into our Pydantic ``VideoScript`` model.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._validate_config()

    def _validate_config(self) -> None:
        provider = self.settings.llm_provider
        if provider == LLMProvider.GROQ and not self.settings.groq_api_key:
            raise ConfigurationError("GROQ_API_KEY is required for LLM provider 'groq'")
        if provider == LLMProvider.OPENAI and not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for LLM provider 'openai'")
        if provider == LLMProvider.ANTHROPIC and not self.settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for LLM provider 'anthropic'")

    def generate(self, request: PipelineRequest) -> VideoScript:
        """Generate and validate a VideoScript for the given request."""
        duration_seconds = int(request.target_duration_seconds or 60)
        target_words = compute_target_words(duration_seconds)
        min_scenes = compute_min_scenes(duration_seconds)
        # Auto-raise scene budget so --duration is not starved by a low --max-scenes.
        effective_max_scenes = max(request.max_scenes, min_scenes)
        if effective_max_scenes > request.max_scenes:
            logger.warning(
                "Raising max_scenes from %d to %d to satisfy 1 scene / 15s for %ds runtime",
                request.max_scenes,
                effective_max_scenes,
                duration_seconds,
            )

        user_prompt = build_user_prompt(
            idea=request.idea,
            style=request.style,
            aspect_ratio=request.aspect_ratio,
            target_duration_seconds=duration_seconds,
            max_scenes=effective_max_scenes,
        )
        logger.info(
            "Generating script | provider=%s | model=%s | style=%s | "
            "duration=%ds | target_words=%d | min_scenes=%d | max_scenes=%d",
            self.settings.llm_provider.value,
            self._resolve_model(),
            request.style.value,
            duration_seconds,
            target_words,
            min_scenes,
            effective_max_scenes,
        )

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                raw = self._call_llm(user_prompt)
                payload = self._parse_json(raw)
                script = self._to_video_script(payload, request)
                # Final hard validation against the Pydantic contract.
                return VideoScript.model_validate(script.model_dump())
            except ConfigurationError:
                # Auth / missing-key problems are not fixable by retrying.
                raise
            except (ScriptGenerationError, ValidationError, ValueError) as exc:
                # Auth failures wrapped as ScriptGenerationError should also fail fast.
                if not _is_retryable_llm_error(exc):
                    raise
                last_error = exc
                logger.warning(
                    "Script generation attempt %d failed validation: %s",
                    attempt,
                    exc,
                )
                user_prompt = (
                    user_prompt
                    + "\n\nIMPORTANT: Your previous response failed validation. "
                    "Return ONLY valid JSON matching the schema exactly."
                )

        raise ScriptGenerationError(
            f"Failed to produce a valid VideoScript after retries: {last_error}"
        ) from last_error

    def _resolve_model(self) -> str:
        if self.settings.llm_provider == LLMProvider.GROQ:
            return self.settings.llm_model or DEFAULT_GROQ_MODEL
        return self.settings.llm_model

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retryable_llm_error),
    )
    def _call_llm(self, user_prompt: str) -> str:
        try:
            if self.settings.llm_provider == LLMProvider.GROQ:
                return self._call_groq(user_prompt)
            if self.settings.llm_provider == LLMProvider.OPENAI:
                return self._call_openai(user_prompt)
            return self._call_anthropic(user_prompt)
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not _is_retryable_llm_error(exc):
                raise ConfigurationError(self._auth_error_message(exc)) from exc
            raise ScriptGenerationError(f"LLM call failed: {exc}") from exc

    def _auth_error_message(self, exc: Exception) -> str:
        provider = self.settings.llm_provider.value
        if provider == "groq":
            return (
                "Groq rejected GROQ_API_KEY (401 invalid_api_key). "
                f"Loaded key preview: {mask_secret(self.settings.groq_api_key)}. "
                "Fix: open .env in the project root and set "
                "GROQ_API_KEY=gsk_... with a valid key from https://console.groq.com/keys "
                "(no quotes/spaces). Then re-run."
            )
        return f"{provider} authentication failed: {exc}"

    def _call_groq(self, user_prompt: str) -> str:
        """Call Groq's OpenAI-compatible Chat Completions API."""
        from openai import AuthenticationError, OpenAI

        api_key = self.settings.groq_api_key
        if not api_key:
            raise ConfigurationError("GROQ_API_KEY is required for LLM provider 'groq'")

        # Groq keys are typically prefixed with gsk_
        if not api_key.startswith("gsk_") and len(api_key) < 20:
            logger.warning(
                "GROQ_API_KEY looks unusual (preview=%s). "
                "Expected a key from https://console.groq.com/keys (usually starts with gsk_).",
                mask_secret(api_key),
            )

        logger.info(
            "Calling Groq | model=%s | key=%s | base_url=%s",
            self._resolve_model(),
            mask_secret(api_key),
            GROQ_BASE_URL,
        )

        client = OpenAI(
            api_key=api_key,
            base_url=GROQ_BASE_URL,
        )
        model = self._resolve_model()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            # Groq natively supports json_object response format.
            response = client.chat.completions.create(
                model=model,
                temperature=0.7,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except AuthenticationError as exc:
            raise ConfigurationError(self._auth_error_message(exc)) from exc

        content = response.choices[0].message.content
        if not content:
            raise ScriptGenerationError("Groq returned empty content")
        logger.debug("Groq raw JSON length=%d", len(content))
        return content

    def _call_openai(self, user_prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0.7,
            response_format={"type": "json_object"},
            messages=messages,
        )
        content = response.choices[0].message.content
        if not content:
            raise ScriptGenerationError("OpenAI returned empty content")
        return content

    def _call_anthropic(self, user_prompt: str) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self.settings.anthropic_api_key)
        message = client.messages.create(
            model=self.settings.llm_model,
            max_tokens=4096,
            temperature=0.7,
            system=(
                SYSTEM_PROMPT
                + " Respond with a single JSON object only — no markdown fences."
            ),
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [
            block.text for block in message.content if getattr(block, "type", "") == "text"
        ]
        content = "\n".join(text_blocks).strip()
        if not content:
            raise ScriptGenerationError("Anthropic returned empty content")
        return content

    def _parse_json(self, raw: str) -> dict[str, Any]:
        """Parse the LLM JSON string into a plain dict for VideoScript mapping."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = _JSON_BLOCK_RE.search(raw)
            if not match:
                raise ScriptGenerationError("LLM response was not valid JSON") from None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise ScriptGenerationError(f"Failed to parse LLM JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ScriptGenerationError("LLM JSON root must be an object")
        return data

    def _to_video_script(self, payload: dict[str, Any], request: PipelineRequest) -> VideoScript:
        scenes_raw = payload.get("scenes") or []
        if not isinstance(scenes_raw, list) or not scenes_raw:
            raise ScriptGenerationError("VideoScript.scenes must be a non-empty list")

        scenes: list[SceneData] = []
        for idx, item in enumerate(scenes_raw):
            if not isinstance(item, dict):
                raise ScriptGenerationError(f"scenes[{idx}] must be an object")
            script_text = str(
                item.get("script_text")
                or item.get("narration")
                or item.get("text")
                or ""
            ).strip()
            visual_prompt = str(item.get("visual_prompt") or "").strip()
            scene_id = int(item.get("scene_id", item.get("index", idx)))
            try:
                scenes.append(
                    SceneData(
                        scene_id=scene_id,
                        script_text=script_text,
                        visual_prompt=visual_prompt,
                        keywords=list(item.get("keywords") or []),
                        duration=float(item.get("duration") or 0.0),
                    )
                )
            except ValidationError as exc:
                raise ScriptGenerationError(f"Invalid scene at index {idx}: {exc}") from exc

        # Normalize contiguous scene_ids starting at 0.
        scenes = [scene.model_copy(update={"scene_id": idx}) for idx, scene in enumerate(scenes)]

        full_script = str(
            payload.get("full_script") or " ".join(s.script_text for s in scenes)
        ).strip()
        style = str(payload.get("style") or request.style.value).strip().lower()

        try:
            package = VideoScript(
                title=str(payload.get("title") or request.idea[:80]).strip(),
                full_script=full_script,
                style=style,
                scenes=scenes,
            )
        except ValidationError as exc:
            raise ScriptGenerationError(f"Invalid VideoScript: {exc}") from exc

        # Only trim if the model wildly overshoots; never trim below cinematic minimum.
        hard_cap = max(request.max_scenes, compute_min_scenes(int(request.target_duration_seconds or 60)))
        if len(package.scenes) > hard_cap:
            trimmed = package.scenes[:hard_cap]
            package = package.model_copy(
                update={
                    "scenes": trimmed,
                    "full_script": " ".join(s.script_text for s in trimmed),
                }
            )

        word_count = len(package.full_script.split())
        logger.info(
            "Script ready | title=%r | scenes=%d | style=%s | word_count=%d | target_words=%d",
            package.title,
            len(package.scenes),
            package.style,
            word_count,
            compute_target_words(int(request.target_duration_seconds or 60)),
        )
        return package
