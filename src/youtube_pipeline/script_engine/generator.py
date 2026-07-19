"""LLM-backed script and visual prompt engine with Structured Outputs."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import LLMProvider, Settings, get_settings
from youtube_pipeline.exceptions import ConfigurationError, ScriptGenerationError
from youtube_pipeline.models import PipelineRequest, SceneData, VideoScript
from youtube_pipeline.script_engine.prompts import SYSTEM_PROMPT, build_user_prompt
from youtube_pipeline.script_engine.schema import openai_response_format
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


class ScriptEngine:
    """Generate a ``VideoScript`` from idea/style via LLM Structured Outputs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._validate_config()

    def _validate_config(self) -> None:
        if self.settings.llm_provider == LLMProvider.OPENAI and not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for LLM provider 'openai'")
        if (
            self.settings.llm_provider == LLMProvider.ANTHROPIC
            and not self.settings.anthropic_api_key
        ):
            raise ConfigurationError("ANTHROPIC_API_KEY is required for LLM provider 'anthropic'")

    def generate(self, request: PipelineRequest) -> VideoScript:
        """Generate and validate a VideoScript for the given request."""
        user_prompt = build_user_prompt(
            idea=request.idea,
            style=request.style,
            aspect_ratio=request.aspect_ratio,
            target_duration_seconds=request.target_duration_seconds,
            max_scenes=request.max_scenes,
        )
        logger.info(
            "Generating script | style=%s | max_scenes=%s",
            request.style.value,
            request.max_scenes,
        )

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                raw = self._call_llm(user_prompt)
                payload = self._parse_json(raw)
                return self._to_video_script(payload, request)
            except (ScriptGenerationError, ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Script generation attempt %d failed validation: %s",
                    attempt,
                    exc,
                )
                # Nudge the model on retry.
                user_prompt = (
                    user_prompt
                    + "\n\nIMPORTANT: Your previous response failed validation. "
                    "Return ONLY valid JSON matching the schema exactly."
                )

        raise ScriptGenerationError(
            f"Failed to produce a valid VideoScript after retries: {last_error}"
        ) from last_error

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _call_llm(self, user_prompt: str) -> str:
        try:
            if self.settings.llm_provider == LLMProvider.OPENAI:
                return self._call_openai(user_prompt)
            return self._call_anthropic(user_prompt)
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ScriptGenerationError(f"LLM call failed: {exc}") from exc

    def _call_openai(self, user_prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Prefer strict Structured Outputs; fall back to json_object for older models.
        try:
            response = client.chat.completions.create(
                model=self.settings.llm_model,
                temperature=0.7,
                response_format=openai_response_format(),
                messages=messages,
            )
        except Exception as structured_exc:  # noqa: BLE001
            logger.warning(
                "Structured Outputs unavailable (%s); falling back to json_object",
                structured_exc,
            )
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
        # Anthropic has no json_schema response_format equivalent here; we rely on
        # the system prompt + Pydantic validation (+ retry in generate()).
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

        if len(package.scenes) > request.max_scenes:
            trimmed = package.scenes[: request.max_scenes]
            package = package.model_copy(
                update={
                    "scenes": trimmed,
                    "full_script": " ".join(s.script_text for s in trimmed),
                }
            )

        logger.info(
            "Script ready | title=%r | scenes=%d | style=%s",
            package.title,
            len(package.scenes),
            package.style,
        )
        return package
