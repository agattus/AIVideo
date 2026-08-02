"""LLM-backed script engine (Gemini primary + optional legacy providers)."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config.settings import LLMProvider, Settings, get_settings, mask_secret
from youtube_pipeline.audio.sfx_tags import apply_sfx_fallback
from youtube_pipeline.exceptions import ConfigurationError, ScriptGenerationError
from youtube_pipeline.models import (
    PipelineRequest,
    QuizMode,
    SceneData,
    VideoFormat,
    VideoScript,
)
from youtube_pipeline.quiz.beats import expand_quiz_questions
from youtube_pipeline.script_engine.prompts import (
    build_system_prompt,
    build_user_prompt,
    build_visual_style_anchor,
    compute_scene_word_budget,
    compute_target_scenes,
    ensure_visual_prompt_has_anchor,
    scene_count_retry_addon,
)
from youtube_pipeline.script_engine.quiz_prompts import (
    build_quiz_system_prompt,
    build_quiz_user_prompt,
)
from youtube_pipeline.script_engine.schema import validate_quiz_script_payload
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")

DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def _is_retryable_llm_error(exc: BaseException) -> bool:
    """Retry transient failures only — never retry bad API keys / auth."""
    if isinstance(exc, ConfigurationError):
        return False
    name = type(exc).__name__
    if name in {"AuthenticationError", "PermissionDeniedError", "InvalidArgument"}:
        return False
    text = str(exc).lower()
    if "api key" in text and ("invalid" in text or "expired" in text or "permission" in text):
        return False
    if "invalid_api_key" in text or "invalid api key" in text:
        return False
    if "authentication" in text and "401" in text:
        return False
    if "403" in text and "key" in text:
        return False
    return True


class ScriptEngine:
    """Generate a ``VideoScript`` via Gemini (JSON mime type) by default.

    Legacy Groq / OpenAI / Anthropic providers remain available when
    ``LLM_PROVIDER`` is set explicitly.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._validate_config()

    def _validate_config(self) -> None:
        provider = self.settings.llm_provider
        if provider == LLMProvider.GEMINI and not self.settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for LLM provider 'gemini'")
        if provider == LLMProvider.GROQ and not self.settings.groq_api_key:
            raise ConfigurationError("GROQ_API_KEY is required for LLM provider 'groq'")
        if provider == LLMProvider.OPENAI and not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for LLM provider 'openai'")
        if provider == LLMProvider.ANTHROPIC and not self.settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is required for LLM provider 'anthropic'")

    def generate(self, request: PipelineRequest) -> VideoScript:
        """Generate and validate a VideoScript for the given request."""
        if request.format == VideoFormat.QUIZVERSE:
            return self._generate_quiz(request)

        duration_seconds = int(request.target_duration_seconds or 60)
        target_scenes = compute_target_scenes(
            max_scenes=int(request.max_scenes),
            duration_seconds=duration_seconds,
        )
        if target_scenes > int(request.max_scenes):
            logger.warning(
                "Raising target_scenes from max_scenes=%d to %d for fast pacing "
                "over %ds runtime (max ~8s/scene)",
                request.max_scenes,
                target_scenes,
                duration_seconds,
            )

        word_budget = compute_scene_word_budget(target_scenes)
        language = getattr(request, "language", None) or "en"
        system_prompt = build_system_prompt(target_scenes, language=language)
        user_prompt = build_user_prompt(
            idea=request.idea,
            style=request.style,
            aspect_ratio=request.aspect_ratio,
            target_duration_seconds=duration_seconds,
            max_scenes=int(request.max_scenes),
            target_scenes=target_scenes,
            language=language,
        )
        # Emphasize constraints once more immediately before the LLM call payload.
        from youtube_pipeline.i18n import script_language_name, normalize_language

        lang_name = script_language_name(normalize_language(language))
        emphasis = (
            f"\n\nFINAL CHECK BEFORE WRITING JSON:\n"
            f"- You MUST generate exactly {target_scenes} scenes.\n"
            f"- Write title, full_script, and every narration in {lang_name} "
            f"(native script — not Latin transliteration).\n"
            f"- visual_prompt stays in English.\n"
            f"- Narration must sound like a gripping Netflix supernatural drama or "
            f"dark thriller documentary — NOT a Wikipedia article.\n"
            f"- NARRATION RULES (exact):\n"
            f"  1. The Cold Open: Start the very first scene with a dark, mysterious, or shocking hook. Do not introduce the main topic immediately. Make the audience ask 'What is happening?'\n"
            f"  2. The Tone: The narration must be intense, suspenseful, and atmospheric. Use sensory words (e.g., 'deafening silence', 'shadows creeping', 'ancient blood').\n"
            f"  3. The Pacing: Use extremely short, punchy sentences. Use ellipses (...) to force dramatic pauses for the TTS engine.\n"
            f"  4. The Escalation: Build the tension scene by scene. Treat the subject matter like a supernatural thriller where the stakes are life and death.\n"
            f"  5. The Climax: End the final scene with a powerful, lingering cliffhanger or a profound, haunting realization.\n"
            f"- Each scene's `narration` MUST be incredibly concise—maximum 15 to 20 words per scene.\n"
            f"- If the narration is longer than 20 words, you must split the concept "
            f"into a new scene with a new `visual_prompt`.\n"
            f"- Never let a single visual linger for more than 2 short sentences.\n"
        )
        user_prompt = user_prompt + emphasis

        logger.info(
            "Generating script | provider=%s | model=%s | style=%s | language=%s | "
            "duration=%ds | target_scenes=%d | word_budget=%d | max_scenes=%d",
            self.settings.llm_provider.value,
            self._resolve_model(),
            request.style.value,
            language,
            duration_seconds,
            target_scenes,
            word_budget,
            request.max_scenes,
        )

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                raw = self._call_llm(user_prompt, system_prompt=system_prompt)
                payload = self._parse_json(raw)
                script = self._to_video_script(
                    payload,
                    request,
                    target_scenes=target_scenes,
                )
                return VideoScript.model_validate(script.model_dump())
            except ConfigurationError:
                raise
            except (ScriptGenerationError, ValidationError, ValueError) as exc:
                if not _is_retryable_llm_error(exc):
                    raise
                last_error = exc
                actual = 0
                msg = str(exc)
                if "got " in msg and "scenes" in msg:
                    try:
                        actual = int(msg.rsplit("got ", 1)[-1].split()[0])
                    except ValueError:
                        actual = 0
                logger.warning(
                    "Script generation attempt %d failed validation: %s",
                    attempt,
                    exc,
                )
                user_prompt = user_prompt + scene_count_retry_addon(
                    target_scenes, actual, language=language
                )

        raise ScriptGenerationError(
            f"Failed to produce a valid VideoScript after retries: {last_error}"
        ) from last_error

    def _generate_quiz(self, request: PipelineRequest) -> VideoScript:
        mode = request.quiz_mode or QuizMode.COMMENT
        default_count = 1 if mode == QuizMode.COMMENT else 5
        requested_count = request.question_count or default_count
        maximum = 5 if mode == QuizMode.COMMENT else 15
        question_count = max(1, min(maximum, requested_count))
        if question_count != requested_count:
            logger.warning(
                "Clamping Quizverse question_count from %d to %d for %s mode",
                requested_count,
                question_count,
                mode.value,
            )

        language = request.language or "en"
        system_prompt = build_quiz_system_prompt(mode, language, question_count)
        user_prompt = build_quiz_user_prompt(
            request.idea,
            mode,
            question_count,
            language,
        )
        last_error: Exception | None = None
        for attempt in range(1, 4):
            raw = self._call_llm(user_prompt, system_prompt=system_prompt)
            try:
                payload = validate_quiz_script_payload(
                    self._parse_json(raw),
                    question_count=question_count,
                )
                questions = payload["questions"]
                scenes = expand_quiz_questions(questions, mode=mode, language=language)
                full_script = " ".join(
                    scene.script_text for scene in scenes if scene.script_text.strip()
                )
                return VideoScript(
                    title=payload["title"],
                    full_script=full_script,
                    style=request.style.value,
                    format=VideoFormat.QUIZVERSE.value,
                    quiz_mode=mode.value,
                    scenes=scenes,
                )
            except (ScriptGenerationError, ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Quizverse generation attempt %d failed validation: %s",
                    attempt,
                    exc,
                )
                if attempt < 3:
                    user_prompt += (
                        "\n\nPREVIOUS RESPONSE WAS INVALID:\n"
                        f"{exc}\n"
                        f"Return corrected JSON with exactly {question_count} questions "
                        "that matches the required schema."
                    )

        raise ScriptGenerationError(
            f"Failed to produce valid Quizverse JSON after 3 attempts: {last_error}"
        ) from last_error

    def _resolve_model(self) -> str:
        if self.settings.llm_provider == LLMProvider.GEMINI:
            return self.settings.llm_model or DEFAULT_GEMINI_MODEL
        if self.settings.llm_provider == LLMProvider.GROQ:
            return self.settings.llm_model or DEFAULT_GROQ_MODEL
        return self.settings.llm_model

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retryable_llm_error),
    )
    def _call_llm(self, user_prompt: str, *, system_prompt: str) -> str:
        try:
            if self.settings.llm_provider == LLMProvider.GEMINI:
                return self._call_gemini(user_prompt, system_prompt=system_prompt)
            if self.settings.llm_provider == LLMProvider.GROQ:
                return self._call_groq(user_prompt, system_prompt=system_prompt)
            if self.settings.llm_provider == LLMProvider.OPENAI:
                return self._call_openai(user_prompt, system_prompt=system_prompt)
            return self._call_anthropic(user_prompt, system_prompt=system_prompt)
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not _is_retryable_llm_error(exc):
                raise ConfigurationError(self._auth_error_message(exc)) from exc
            raise ScriptGenerationError(f"LLM call failed: {exc}") from exc

    def _auth_error_message(self, exc: Exception) -> str:
        provider = self.settings.llm_provider.value
        if provider == "gemini":
            return (
                "Gemini rejected GEMINI_API_KEY. "
                f"Loaded key preview: {mask_secret(self.settings.gemini_api_key)}. "
                "Fix: set GEMINI_API_KEY in .env (no quotes) from Google AI Studio, then re-run."
            )
        if provider == "groq":
            return (
                "Groq rejected GROQ_API_KEY (401 invalid_api_key). "
                f"Loaded key preview: {mask_secret(self.settings.groq_api_key)}. "
                "Fix: set GROQ_API_KEY=gsk_... in .env (no quotes)."
            )
        return f"{provider} authentication failed: {exc}"

    def _call_gemini(self, user_prompt: str, *, system_prompt: str) -> str:
        """Call Google Gemini with forced JSON mime type (no markdown fences)."""
        import google.generativeai as genai

        api_key = self.settings.gemini_api_key
        if not api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for LLM provider 'gemini'")

        model_name = self._resolve_model()
        logger.info(
            "Calling Gemini | model=%s | key=%s | system_chars=%d",
            model_name,
            mask_secret(api_key),
            len(system_prompt),
        )

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            generation_config={
                "temperature": 0.7,
                "response_mime_type": "application/json",
            },
        )
        response = model.generate_content(user_prompt)
        content = getattr(response, "text", None)
        if not content:
            # Some SDK versions expose candidates instead of .text
            try:
                content = response.candidates[0].content.parts[0].text
            except Exception as exc:  # noqa: BLE001
                raise ScriptGenerationError(f"Gemini returned empty content: {exc}") from exc
        content = str(content).strip()
        if not content:
            raise ScriptGenerationError("Gemini returned empty content")
        logger.debug("Gemini raw JSON length=%d", len(content))
        return content

    def _call_groq(self, user_prompt: str, *, system_prompt: str) -> str:
        from openai import OpenAI

        api_key = self.settings.groq_api_key
        if not api_key:
            raise ConfigurationError("GROQ_API_KEY is required for LLM provider 'groq'")

        client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        response = client.chat.completions.create(
            model=self._resolve_model(),
            temperature=0.7,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ScriptGenerationError("Groq returned empty content")
        return content

    def _call_openai(self, user_prompt: str, *, system_prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        response = client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0.7,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ScriptGenerationError("OpenAI returned empty content")
        return content

    def _call_anthropic(self, user_prompt: str, *, system_prompt: str) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self.settings.anthropic_api_key)
        message = client.messages.create(
            model=self.settings.llm_model,
            max_tokens=4096,
            temperature=0.7,
            system=system_prompt + " Respond with a single JSON value only — no markdown fences.",
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
        """Parse Gemini/LLM JSON into a dict (supports object or bare scenes array)."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = _JSON_OBJECT_RE.search(raw) or _JSON_ARRAY_RE.search(raw)
            if not match:
                raise ScriptGenerationError("LLM response was not valid JSON") from None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise ScriptGenerationError(f"Failed to parse LLM JSON: {exc}") from exc

        if isinstance(data, list):
            return {"scenes": data}
        if isinstance(data, dict):
            return data
        raise ScriptGenerationError("LLM JSON root must be an object or array of scenes")

    def _to_video_script(
        self,
        payload: dict[str, Any],
        request: PipelineRequest,
        *,
        target_scenes: int,
    ) -> VideoScript:
        scenes_raw = payload.get("scenes") or []
        if not isinstance(scenes_raw, list) or not scenes_raw:
            raise ScriptGenerationError("VideoScript.scenes must be a non-empty list")

        if len(scenes_raw) < target_scenes:
            raise ScriptGenerationError(
                f"Expected exactly {target_scenes} scenes, got {len(scenes_raw)}"
            )

        style_anchor = build_visual_style_anchor(idea=request.idea, style=request.style)

        scenes: list[SceneData] = []
        for idx, item in enumerate(scenes_raw):
            if not isinstance(item, dict):
                raise ScriptGenerationError(f"scenes[{idx}] must be an object")
            # Prefer Gemini "narration"; keep script_text / text as aliases.
            script_text = str(
                item.get("narration")
                or item.get("script_text")
                or item.get("text")
                or ""
            ).strip()
            visual_prompt = ensure_visual_prompt_has_anchor(
                str(item.get("visual_prompt") or "").strip(),
                style_anchor,
            )
            scene_id = int(item.get("scene_id", item.get("index", idx)))
            try:
                scene = SceneData(
                    scene_id=scene_id,
                    script_text=script_text,
                    visual_prompt=visual_prompt,
                    keywords=list(item.get("keywords") or []),
                    duration=float(item.get("duration") or 0.0),
                    ambience=item.get("ambience", "none"),
                    sfx=item.get("sfx", []),
                )
                scenes.append(apply_sfx_fallback(scene))
            except ValidationError as exc:
                raise ScriptGenerationError(f"Invalid scene at index {idx}: {exc}") from exc

        # Enforce exact target: drop extras if the model overshot.
        if len(scenes) > target_scenes:
            logger.warning(
                "Trimming scenes from %d to exact target_scenes=%d",
                len(scenes),
                target_scenes,
            )
            scenes = scenes[:target_scenes]

        scenes = [scene.model_copy(update={"scene_id": idx}) for idx, scene in enumerate(scenes)]
        if len(scenes) != target_scenes:
            raise ScriptGenerationError(
                f"Expected exactly {target_scenes} scenes, got {len(scenes)}"
            )

        long_scenes = [
            (s.scene_id, len(s.script_text.split()))
            for s in scenes
            if len(s.script_text.split()) > 20
        ]
        if long_scenes:
            # Retry so the model splits verbose beats into extra scenes.
            details = ", ".join(f"scene {sid}={words}w" for sid, words in long_scenes[:6])
            raise ScriptGenerationError(
                f"Expected exactly {target_scenes} scenes with ≤20 words each; "
                f"got {len(scenes)} scenes with verbose narration ({details})"
            )

        logger.info(
            "Visual character lock applied | anchor=%r | scenes=%d",
            style_anchor,
            len(scenes),
        )

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

        # Keep full_script aligned with the accepted scene set.
        package = package.model_copy(
            update={"full_script": " ".join(s.script_text for s in package.scenes)}
        )

        word_count = len(package.full_script.split())
        logger.info(
            "Script ready | title=%r | scenes=%d (target=%d) | style=%s | "
            "word_count=%d | word_budget=%d",
            package.title,
            len(package.scenes),
            target_scenes,
            package.style,
            word_count,
            compute_scene_word_budget(target_scenes),
        )
        return package
