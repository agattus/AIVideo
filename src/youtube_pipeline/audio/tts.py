"""Text-to-speech providers (OpenAI / ElevenLabs) with scene duration timing."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import Settings, TTSProvider, get_settings
from youtube_pipeline.exceptions import AudioGenerationError, ConfigurationError
from youtube_pipeline.models import BeatType, SceneData, VideoScript, WordTimestamp
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

# Average conversational narration rate used when forced alignment is unavailable.
WORDS_PER_MINUTE = 150.0
SECONDS_PER_WORD = 60.0 / WORDS_PER_MINUTE  # 0.4s
_SCENE_PAUSE_JOIN = " ... "
_DIALOGUE_LINE_PAUSE_MS = 300

_WORD_RE = re.compile(r"\S+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _resolve_ffmpeg() -> str:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise AudioGenerationError(f"ffmpeg binary not found: {exc}") from exc


class TTSResult(BaseModel):
    """Artifacts returned by a successful TTS run."""

    model_config = ConfigDict(extra="forbid")

    audio_path: Path
    duration_seconds: float = Field(gt=0.0)
    script: VideoScript
    word_timestamps: list[WordTimestamp] = Field(default_factory=list)
    timing: dict[str, Any] = Field(
        default_factory=dict,
        description="Word/sentence timing dictionary used to populate scene durations",
    )


class AudioEngine:
    """Convert a VideoScript into voiceover.mp3 and populate scene durations.

    Timing strategy
    ---------------
    1. Synthesize the full script (or concatenated scene texts) to ``voiceover.mp3``.
    2. Probe the real audio duration from the file.
    3. Build word-level timestamps by distributing time proportional to word length,
       scaled so the last word ends exactly at the probed duration.
    4. If probing fails, fall back to ~150 WPM estimated duration.
    5. Aggregate word spans back onto each scene's ``script_text`` and write
       ``SceneData.duration``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._validate_config()

    def _validate_config(self) -> None:
        if self.settings.tts_provider == TTSProvider.OPENAI and not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for TTS provider 'openai'")
        if self.settings.tts_provider == TTSProvider.ELEVENLABS:
            if not self.settings.elevenlabs_api_key:
                raise ConfigurationError(
                    "ELEVENLABS_API_KEY is required for TTS provider 'elevenlabs'"
                )
            # ELEVENLABS_VOICE_ID is optional: dialogue uses voice_map; narration
            # falls back to the first voice in the account catalog.
        if self.settings.tts_provider == TTSProvider.GTTS:
            # gTTS is keyless; verify the package is importable early.
            try:
                import gtts  # noqa: F401
            except ImportError as exc:
                raise ConfigurationError(
                    "TTS_PROVIDER=gtts requires the 'gTTS' package. "
                    "Install with: pip install gTTS"
                ) from exc
        if self.settings.tts_provider == TTSProvider.EDGE_TTS:
            try:
                import edge_tts  # noqa: F401
            except ImportError as exc:
                raise ConfigurationError(
                    "TTS_PROVIDER=edge-tts requires the 'edge-tts' package. "
                    "Install with: pip install edge-tts"
                ) from exc

    def synthesize(
        self,
        script: VideoScript,
        output_dir: Path | str,
        *,
        voice: str | None = None,
        use_per_scene_text: bool = False,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> TTSResult:
        """Generate ``voiceover.mp3`` and return a script with scene durations set.

        Parameters
        ----------
        script:
            Untimed (or previously timed) video script.
        output_dir:
            Directory where ``voiceover.mp3`` will be written.
        voice:
            Optional provider voice override.
        use_per_scene_text:
            When True, concatenate each scene's ``script_text`` instead of
            ``full_script`` (useful if the LLM full_script drifts from scenes).
        """
        output_path = ensure_dir(Path(output_dir))
        audio_path = output_path / "voiceover.mp3"

        if script.format == "dialogue" and script.lines:
            try:
                return self._synthesize_dialogue_lines(
                    script,
                    audio_path,
                    on_progress=on_progress,
                )
            except ConfigurationError:
                raise
            except Exception as exc:  # noqa: BLE001
                from youtube_pipeline.audio.elevenlabs_voices import (
                    ELEVENLABS_PAID_PLAN_MESSAGE,
                    is_elevenlabs_paid_plan_error,
                )

                if (
                    self.settings.tts_provider == TTSProvider.ELEVENLABS
                    and is_elevenlabs_paid_plan_error(exc)
                ):
                    logger.warning(
                        "ElevenLabs library voices blocked on free plan; "
                        "falling back to Edge multi-voice for dialogue"
                    )
                    try:
                        return self._synthesize_dialogue_edge_fallback(
                            script,
                            audio_path,
                            on_progress=on_progress,
                        )
                    except Exception as fallback_exc:  # noqa: BLE001
                        raise AudioGenerationError(
                            f"{ELEVENLABS_PAID_PLAN_MESSAGE} Edge fallback also failed: {fallback_exc}"
                        ) from fallback_exc
                if is_elevenlabs_paid_plan_error(exc):
                    raise AudioGenerationError(ELEVENLABS_PAID_PLAN_MESSAGE) from exc
                raise AudioGenerationError(
                    f"Dialogue TTS synthesis failed: {exc}"
                ) from exc

        # Quizverse timing is part of the audio contract for every provider.
        # Never fall back to one-shot narration because that would drop timer
        # silence and hold padding while still returning apparently valid audio.
        if script.format == "quizverse":
            try:
                return self._synthesize_with_scene_pauses(
                    script,
                    audio_path,
                    voice=voice,
                    on_progress=on_progress,
                )
            except ConfigurationError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise AudioGenerationError(
                    f"Quizverse TTS synthesis failed: {exc}"
                ) from exc

        # Multi-scene Edge TTS: real silence gaps between scenes for pacing.
        if (
            self.settings.tts_provider == TTSProvider.EDGE_TTS
            and len(script.scenes) > 1
        ):
            try:
                return self._synthesize_with_scene_pauses(
                    script,
                    audio_path,
                    voice=voice,
                    on_progress=on_progress,
                )
            except ConfigurationError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Per-scene edge-tts failed (%s); falling back to one-shot with pauses",
                    exc,
                )

        text = self._resolve_narration_text(
            script,
            use_per_scene_text=use_per_scene_text
            or self.settings.tts_provider == TTSProvider.EDGE_TTS,
            scene_pause_join=self.settings.tts_provider == TTSProvider.EDGE_TTS,
        )
        if not text.strip():
            raise AudioGenerationError("Cannot synthesize empty narration text")

        logger.info(
            "Synthesizing voiceover | provider=%s | chars=%d",
            self.settings.tts_provider.value,
            len(text),
        )

        try:
            self._synthesize_for_provider(text, audio_path, voice=voice)
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            from youtube_pipeline.audio.elevenlabs_voices import (
                ELEVENLABS_PAID_PLAN_MESSAGE,
                is_elevenlabs_paid_plan_error,
            )

            if (
                self.settings.tts_provider == TTSProvider.ELEVENLABS
                and is_elevenlabs_paid_plan_error(exc)
            ):
                logger.warning(
                    "ElevenLabs library voice blocked on free plan; falling back to Edge TTS"
                )
                from youtube_pipeline.i18n import default_voice_for_language

                edge_settings = self.settings.model_copy(
                    update={"tts_provider": TTSProvider.EDGE_TTS}
                )
                edge_voice = default_voice_for_language("en")
                try:
                    AudioEngine(edge_settings)._synthesize_edge_tts(
                        text, audio_path, voice=edge_voice
                    )
                except Exception as fallback_exc:  # noqa: BLE001
                    raise AudioGenerationError(
                        f"{ELEVENLABS_PAID_PLAN_MESSAGE} Edge fallback also failed: {fallback_exc}"
                    ) from fallback_exc
            elif is_elevenlabs_paid_plan_error(exc):
                raise AudioGenerationError(ELEVENLABS_PAID_PLAN_MESSAGE) from exc
            else:
                raise AudioGenerationError(f"TTS synthesis failed: {exc}") from exc

        if not audio_path.exists() or audio_path.stat().st_size == 0:
            raise AudioGenerationError(f"TTS produced empty audio file: {audio_path}")

        duration = self._probe_duration_seconds(audio_path)
        if duration <= 0:
            duration = self.estimate_duration_wpm(text)
            logger.warning(
                "Audio probe failed; using 150 WPM estimate (%.2fs)",
                duration,
            )

        word_timestamps = self._estimate_word_timestamps(text, duration)
        timing = self._build_timing_dictionary(script, word_timestamps, duration)
        timed_script = self._apply_scene_durations(script, timing, duration)

        result = TTSResult(
            audio_path=audio_path,
            duration_seconds=duration,
            script=timed_script,
            word_timestamps=word_timestamps,
            timing=timing,
        )
        logger.info(
            "Audio ready | duration=%.2fs | scenes=%d | words=%d",
            result.duration_seconds,
            len(timed_script.scenes),
            len(word_timestamps),
        )
        return result

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_duration_wpm(text: str, *, wpm: float = WORDS_PER_MINUTE) -> float:
        """Estimate spoken duration from average speaking rate (~150 WPM)."""
        words = _WORD_RE.findall(text)
        if not words:
            return 0.5
        rate = wpm if wpm > 0 else WORDS_PER_MINUTE
        return max(0.5, len(words) * (60.0 / rate))

    def populate_scene_durations(
        self,
        script: VideoScript,
        *,
        total_duration: float | None = None,
    ) -> VideoScript:
        """Populate ``SceneData.duration`` without calling a TTS API.

        Useful for dry-runs and tests. Durations are proportional to each
        scene's word count and scaled to ``total_duration`` when provided,
        otherwise estimated at 150 WPM.
        """
        text = self._resolve_narration_text(script, use_per_scene_text=True)
        duration = (
            float(total_duration)
            if total_duration and total_duration > 0
            else self.estimate_duration_wpm(text)
        )
        words = self._estimate_word_timestamps(text, duration)
        timing = self._build_timing_dictionary(script, words, duration)
        return self._apply_scene_durations(script, timing, duration)

    # ------------------------------------------------------------------
    # Provider calls
    # ------------------------------------------------------------------

    def _synthesize_for_provider(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None,
    ) -> None:
        """Synthesize one speech clip with the configured provider."""
        if self.settings.tts_provider == TTSProvider.OPENAI:
            self._synthesize_openai(text, output_path, voice=voice)
        elif self.settings.tts_provider == TTSProvider.ELEVENLABS:
            self._synthesize_elevenlabs(text, output_path, voice=voice)
        elif self.settings.tts_provider == TTSProvider.GTTS:
            self._synthesize_gtts(text, output_path, voice=voice)
        elif self.settings.tts_provider == TTSProvider.EDGE_TTS:
            self._synthesize_edge_tts(text, output_path, voice=voice)
        else:
            raise ConfigurationError(
                f"Unsupported TTS provider: {self.settings.tts_provider!r}"
            )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _synthesize_openai(self, text: str, output_path: Path, *, voice: str | None) -> None:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        try:
            with client.audio.speech.with_streaming_response.create(
                model=self.settings.openai_tts_model,
                voice=voice or self.settings.openai_tts_voice,
                input=text,
                response_format="mp3",
            ) as response:
                response.stream_to_file(output_path)
        except TypeError:
            # Older openai SDK builds may not accept response_format.
            with client.audio.speech.with_streaming_response.create(
                model=self.settings.openai_tts_model,
                voice=voice or self.settings.openai_tts_voice,
                input=text,
            ) as response:
                response.stream_to_file(output_path)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _synthesize_elevenlabs(self, text: str, output_path: Path, *, voice: str | None) -> None:
        from elevenlabs import ElevenLabs

        from youtube_pipeline.audio.elevenlabs_voices import default_elevenlabs_voice_id

        client = ElevenLabs(api_key=self.settings.elevenlabs_api_key)
        voice_id = (voice or self.settings.elevenlabs_voice_id or "").strip()
        if not voice_id:
            voice_id = default_elevenlabs_voice_id() or ""
        if not voice_id:
            raise ConfigurationError(
                "ElevenLabs voice id is missing. Set ELEVENLABS_VOICE_ID or assign cast voices."
            )

        audio_iter = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        with output_path.open("wb") as fh:
            for chunk in audio_iter:
                if chunk:
                    fh.write(chunk)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _synthesize_gtts(self, text: str, output_path: Path, *, voice: str | None) -> None:
        """Synthesize speech with Google Translate TTS (keyless, free-tier friendly).

        ``voice`` may be a BCP-47 language code (e.g. ``en``, ``en-uk``, ``es``).
        Defaults to ``en``.
        """
        from gtts import gTTS

        lang = (voice or "en").strip().lower()
        # gTTS accepts short codes like "en" / "en-uk"; normalize "en_US" → "en".
        if "_" in lang:
            lang = lang.replace("_", "-")
        tts = gTTS(text=text, lang=lang.split("-")[0] if len(lang) > 5 else lang)
        tts.save(str(output_path))

    def _edge_tts_prosody(self) -> tuple[str, str, str, str]:
        """Return ``(voice, rate, pitch, volume)`` defaults for Edge TTS."""
        voice = str(getattr(self.settings, "edge_tts_voice", None) or "en-US-AriaNeural").strip()
        rate = str(getattr(self.settings, "edge_tts_rate", None) or "-20%").strip()
        pitch = str(getattr(self.settings, "edge_tts_pitch", None) or "+2Hz").strip()
        volume = str(getattr(self.settings, "edge_tts_volume", None) or "+0%").strip()
        return voice, rate, pitch, volume

    def _edge_tts_scene_pause_ms(self) -> int:
        raw = getattr(self.settings, "edge_tts_scene_pause_ms", 450)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 450

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _synthesize_edge_tts(self, text: str, output_path: Path, *, voice: str | None) -> None:
        """Synthesize speech with Microsoft Edge neural TTS (keyless).

        ``voice`` overrides ``settings.edge_tts_voice`` (e.g. ``en-US-JennyNeural``).
        """
        import edge_tts

        from youtube_pipeline.utils.async_run import run_coro_sync

        default_voice, rate, pitch, volume = self._edge_tts_prosody()
        selected_voice = (voice or default_voice).strip()
        logger.info(
            "edge-tts voice=%s | rate=%s | pitch=%s | out=%s",
            selected_voice,
            rate,
            pitch,
            output_path,
        )

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text,
                selected_voice,
                rate=rate,
                pitch=pitch,
                volume=volume,
            )
            await communicate.save(str(output_path))

        # Voiceover update runs inside FastAPI's async loop; never nest asyncio.run.
        run_coro_sync(_run)

    def _synthesize_with_scene_pauses(
        self,
        script: VideoScript,
        output_path: Path,
        *,
        voice: str | None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> TTSResult:
        """Synthesize each scene, insert silence gaps, and time from measured clips."""
        is_quizverse = script.format == "quizverse"
        pause_ms = 0 if is_quizverse else self._edge_tts_scene_pause_ms()
        pause_s = pause_ms / 1000.0
        work = Path(tempfile.mkdtemp(prefix="tts_scenes_", dir=str(output_path.parent)))
        scene_clips: list[Path] = []
        speech_durations: list[float] = []
        total_scenes = len(script.scenes)

        def _progress(done: int, message: str) -> None:
            if on_progress is None:
                return
            try:
                on_progress(done, total_scenes, message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS progress callback failed | %s", exc)

        try:
            for index, scene in enumerate(script.scenes):
                _progress(
                    index,
                    f"Recording narration for scene {index + 1} of {total_scenes}…",
                )
                text = (scene.script_text or "").strip()
                clip = work / f"scene_{int(scene.scene_id):04d}.mp3"
                hold_s = (
                    max(0.05, float(scene.hold_seconds))
                    if is_quizverse and scene.hold_seconds is not None
                    else None
                )
                is_silent_beat = is_quizverse and (
                    scene.beat_type == BeatType.TIMER or not text
                )

                if is_silent_beat:
                    silence_s = hold_s or 0.05
                    self._make_silence_mp3(
                        clip,
                        pause_ms=int(silence_s * 1000),
                    )
                    dur = silence_s
                else:
                    if not text:
                        raise AudioGenerationError(
                            f"Scene {scene.scene_id} has empty narration for TTS"
                        )
                    self._synthesize_for_provider(text, clip, voice=voice)
                    if not clip.exists() or clip.stat().st_size == 0:
                        raise AudioGenerationError(
                            f"TTS produced empty audio for scene {scene.scene_id}"
                        )
                    dur = self._probe_duration_seconds(clip)
                    if dur <= 0:
                        dur = self.estimate_duration_wpm(text)

                    if hold_s is not None and dur < hold_s:
                        speech_clip = work / f"speech_{int(scene.scene_id):04d}.mp3"
                        padding_clip = work / f"padding_{int(scene.scene_id):04d}.mp3"
                        clip.replace(speech_clip)
                        self._make_silence_mp3(
                            padding_clip,
                            pause_ms=int((hold_s - dur) * 1000),
                        )
                        self._concat_mp3_with_silence(
                            [speech_clip, padding_clip],
                            clip,
                            pause_ms=0,
                        )
                        dur = hold_s

                if not clip.exists() or clip.stat().st_size == 0:
                    raise AudioGenerationError(
                        f"TTS produced empty audio for scene {scene.scene_id}"
                    )
                scene_clips.append(clip)
                speech_durations.append(float(dur))

            _progress(total_scenes, "Stitching narration with scene pauses…")
            self._concat_mp3_with_silence(scene_clips, output_path, pause_ms=pause_ms)

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AudioGenerationError(f"TTS produced empty audio file: {output_path}")

            total = sum(speech_durations) + pause_s * max(0, len(speech_durations) - 1)
            if not is_quizverse:
                probed = self._probe_duration_seconds(output_path)
                if probed > 0:
                    total = probed

            timing = self._build_timing_from_scene_speech(
                script, speech_durations, pause_s=pause_s, total_duration=total
            )
            timed_script = self._apply_scene_durations(script, timing, total)
            word_timestamps = [
                WordTimestamp.model_validate(item) for item in timing.get("words", [])
            ]

            result = TTSResult(
                audio_path=output_path,
                duration_seconds=total,
                script=timed_script,
                word_timestamps=word_timestamps,
                timing=timing,
            )
            logger.info(
                "Audio ready (per-scene pauses) | duration=%.2fs | scenes=%d | pause_ms=%d",
                result.duration_seconds,
                len(timed_script.scenes),
                pause_ms,
            )
            return result
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _synthesize_dialogue_edge_fallback(
        self,
        script: VideoScript,
        output_path: Path,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> TTSResult:
        """Remap cast to Edge voices and synthesize when ElevenLabs plan blocks library voices."""
        from youtube_pipeline.dialogue.casting import assign_voices

        language = "en"
        try:
            # Optional language field may exist on persisted scripts.
            language = str(getattr(script, "language", None) or "en")
        except Exception:  # noqa: BLE001
            language = "en"

        edge_map = assign_voices(
            list(script.cast or []),
            language=language,
            provider=TTSProvider.EDGE_TTS,
        )
        fallback_script = script.model_copy(update={"voice_map": edge_map})
        edge_settings = self.settings.model_copy(
            update={"tts_provider": TTSProvider.EDGE_TTS}
        )
        edge_engine = AudioEngine(edge_settings)
        result = edge_engine._synthesize_dialogue_lines(
            fallback_script,
            output_path,
            on_progress=on_progress,
        )
        # Persist remapped Edge voices on the timed script for Studio.
        result.script = result.script.model_copy(update={"voice_map": edge_map})
        return result

    def _synthesize_dialogue_lines(
        self,
        script: VideoScript,
        output_path: Path,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> TTSResult:
        """Synthesize dialogue line-by-line with each character's assigned voice."""
        pause_s = _DIALOGUE_LINE_PAUSE_MS / 1000.0
        work = Path(tempfile.mkdtemp(prefix="tts_dialogue_", dir=str(output_path.parent)))
        line_clips: list[Path] = []
        speech_durations: list[float] = []
        total_lines = len(script.lines)
        cast_names = {
            str(member.get("id") or "").strip(): str(member.get("name") or "").strip()
            for member in script.cast
        }

        def _progress(done: int, message: str) -> None:
            if on_progress is None:
                return
            try:
                on_progress(done, total_lines, message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS progress callback failed | %s", exc)

        try:
            normalized_lines: list[dict[str, str]] = []
            for index, line in enumerate(script.lines):
                speaker_id = str(line.get("speaker_id") or "").strip()
                text = str(line.get("text") or "").strip()
                speaker_name = str(
                    line.get("speaker_name") or cast_names.get(speaker_id) or ""
                ).strip()
                selected_voice = str(script.voice_map.get(speaker_id) or "").strip()
                if not speaker_id or not text:
                    raise AudioGenerationError(
                        f"Dialogue line {index} requires speaker_id and text"
                    )
                if not selected_voice:
                    raise AudioGenerationError(
                        f"Dialogue speaker {speaker_id!r} has no assigned voice"
                    )

                _progress(
                    index,
                    f"Recording dialogue line {index + 1} of {total_lines}…",
                )
                clip = work / f"line_{index:04d}.mp3"
                try:
                    self._synthesize_for_provider(text, clip, voice=selected_voice)
                except Exception as exc:  # noqa: BLE001
                    # Retired Edge voices (e.g. en-US-DavisNeural) raise NoAudioReceived.
                    if self.settings.tts_provider != TTSProvider.EDGE_TTS:
                        raise
                    from youtube_pipeline.i18n import default_voice_for_language

                    fallback_voice = default_voice_for_language(
                        str(getattr(script, "language", None) or "en")
                    )
                    if (
                        "NoAudioReceived" not in type(exc).__name__
                        and "No audio was received" not in str(exc)
                    ) or fallback_voice == selected_voice:
                        raise
                    logger.warning(
                        "Dialogue edge-tts failed for voice=%s (%s); retrying with %s",
                        selected_voice,
                        exc,
                        fallback_voice,
                    )
                    self._synthesize_edge_tts(text, clip, voice=fallback_voice)
                if not clip.exists() or clip.stat().st_size == 0:
                    raise AudioGenerationError(
                        f"TTS produced empty audio for dialogue line {index}"
                    )
                duration = self._probe_duration_seconds(clip)
                if duration <= 0:
                    duration = self.estimate_duration_wpm(text)
                line_clips.append(clip)
                speech_durations.append(float(duration))
                normalized_lines.append(
                    {
                        "speaker_id": speaker_id,
                        "speaker_name": speaker_name,
                        "text": text,
                    }
                )

            _progress(total_lines, "Stitching character dialogue…")
            self._concat_mp3_with_silence(
                line_clips,
                output_path,
                pause_ms=_DIALOGUE_LINE_PAUSE_MS,
            )
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AudioGenerationError(f"TTS produced empty audio file: {output_path}")

            total = sum(speech_durations) + pause_s * max(0, total_lines - 1)
            probed = self._probe_duration_seconds(output_path)
            if probed > 0:
                total = probed
            timing = self._build_dialogue_timing(
                script,
                normalized_lines,
                speech_durations,
                pause_s=pause_s,
                total_duration=total,
            )
            timed_script = self._apply_scene_durations(script, timing, total)
            word_timestamps = [
                WordTimestamp.model_validate(item) for item in timing.get("words", [])
            ]
            return TTSResult(
                audio_path=output_path,
                duration_seconds=total,
                script=timed_script,
                word_timestamps=word_timestamps,
                timing=timing,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _build_dialogue_timing(
        self,
        script: VideoScript,
        lines: list[dict[str, str]],
        speech_durations: list[float],
        *,
        pause_s: float,
        total_duration: float,
    ) -> dict[str, Any]:
        """Build line and visual-scene timing from measured dialogue clips."""
        if len(lines) != len(speech_durations):
            raise AudioGenerationError(
                "Dialogue line duration count does not match script lines"
            )

        cursor = 0.0
        line_timings: list[dict[str, Any]] = []
        words: list[WordTimestamp] = []
        for index, (line, speech) in enumerate(
            zip(lines, speech_durations, strict=True)
        ):
            speech = max(0.05, float(speech))
            start = cursor
            local_words = self._estimate_word_timestamps(line["text"], speech)
            words.extend(
                WordTimestamp(
                    word=item.word,
                    start=start + float(item.start),
                    end=start + float(item.end),
                )
                for item in local_words
            )
            gap = pause_s if index < len(lines) - 1 else 0.0
            end = start + speech + gap
            line_timings.append({**line, "start": float(start), "end": float(end)})
            cursor = end

        if line_timings and total_duration > 0:
            drift = float(total_duration) - cursor
            if abs(drift) > 0.01:
                line_timings[-1]["end"] = float(line_timings[-1]["end"] + drift)

        scene_timings: list[dict[str, Any]] = []
        for scene in script.scenes:
            line_start = scene.line_start
            line_end = scene.line_end
            if (
                line_start is None
                or line_end is None
                or line_start < 0
                or line_end < line_start
                or line_end >= len(line_timings)
            ):
                raise AudioGenerationError(
                    f"Scene {scene.scene_id} has an invalid dialogue line range"
                )
            selected = line_timings[line_start : line_end + 1]
            duration = sum(float(item["end"]) - float(item["start"]) for item in selected)
            scene_timings.append(
                {
                    "scene_id": scene.scene_id,
                    "start": float(selected[0]["start"]),
                    "end": float(selected[-1]["end"]),
                    "duration": float(max(0.05, duration)),
                    "word_count": max(1, len(_WORD_RE.findall(scene.script_text))),
                }
            )

        narration = " ".join(line["text"] for line in lines)
        return {
            "total_duration": float(total_duration),
            "words_per_minute": WORDS_PER_MINUTE,
            "scene_pause_seconds": 0.0,
            "words": [word.model_dump() for word in words],
            "sentences": self._estimate_sentence_timestamps(narration, total_duration),
            "lines": line_timings,
            "scenes": scene_timings,
        }

    def _concat_mp3_with_silence(
        self,
        clips: list[Path],
        dest: Path,
        *,
        pause_ms: int,
    ) -> None:
        """Concatenate MP3 clips with ``pause_ms`` of silence between each pair."""
        if not clips:
            raise AudioGenerationError("No scene clips to concatenate")
        if len(clips) == 1:
            shutil.copyfile(clips[0], dest)
            return

        ffmpeg = _resolve_ffmpeg()
        work = dest.parent / f"_concat_{dest.stem}"
        ensure_dir(work)
        silence: Path | None = None
        try:
            inputs: list[Path] = []
            for index, clip in enumerate(clips):
                inputs.append(clip)
                if index < len(clips) - 1 and pause_ms > 0:
                    if silence is None:
                        silence = work / "silence.mp3"
                        self._make_silence_mp3(silence, pause_ms=pause_ms, ffmpeg=ffmpeg)
                    inputs.append(silence)

            # Re-encode concat so mismatched Edge TTS frames still join cleanly.
            cmd: list[str] = [ffmpeg, "-y"]
            for path in inputs:
                cmd.extend(["-i", str(path)])
            n = len(inputs)
            filter_parts = "".join(f"[{i}:a]" for i in range(n))
            cmd.extend(
                [
                    "-filter_complex",
                    f"{filter_parts}concat=n={n}:v=0:a=1[a]",
                    "-map",
                    "[a]",
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    "4",
                    str(dest),
                ]
            )
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0 or not dest.exists():
                tail = (proc.stderr or proc.stdout or "")[-800:]
                raise AudioGenerationError(
                    f"ffmpeg scene-pause concat failed ({proc.returncode}): {tail}"
                )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _make_silence_mp3(self, dest: Path, *, pause_ms: int, ffmpeg: str | None = None) -> None:
        """Write a short silent MP3 of ``pause_ms`` duration."""
        exe = ffmpeg or _resolve_ffmpeg()
        seconds = max(0.05, pause_ms / 1000.0)
        cmd = [
            exe,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            f"{seconds:.3f}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "9",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
            tail = (proc.stderr or proc.stdout or "")[-400:]
            raise AudioGenerationError(
                f"ffmpeg silence generation failed ({proc.returncode}): {tail}"
            )

    def _build_timing_from_scene_speech(
        self,
        script: VideoScript,
        speech_durations: list[float],
        *,
        pause_s: float,
        total_duration: float,
    ) -> dict[str, Any]:
        """Build timing dict from measured per-scene speech lengths + pause gaps."""
        if len(speech_durations) != len(script.scenes):
            raise AudioGenerationError(
                "Scene speech duration count does not match script scenes"
            )

        cursor = 0.0
        scene_timings: list[dict[str, Any]] = []
        for index, (scene, speech) in enumerate(
            zip(script.scenes, speech_durations, strict=True)
        ):
            gap = pause_s if index < len(script.scenes) - 1 else 0.0
            start = cursor
            end = cursor + float(speech) + gap
            scene_timing = {
                "scene_id": scene.scene_id,
                "start": float(start),
                "end": float(end),
                "duration": float(max(0.05, end - start)),
                "speech_duration": float(speech),
                "pause_after": float(gap),
                "word_count": max(1, len(_WORD_RE.findall(scene.script_text))),
            }
            if script.format == "quizverse":
                scene_timing["beat_type"] = scene.beat_type.value
            scene_timings.append(scene_timing)
            cursor = end

        # Absorb probe drift into the final scene so sum matches total_duration.
        if scene_timings and total_duration > 0:
            drift = float(total_duration) - cursor
            if abs(drift) > 0.01:
                last = scene_timings[-1]
                last["end"] = float(last["end"] + drift)
                last["duration"] = float(max(0.05, last["duration"] + drift))

        # Words live only inside speech windows — never across silence gaps —
        # so burned-in captions stay locked to the spoken audio.
        words = self._estimate_word_timestamps_with_pauses(
            script, speech_durations, pause_s=pause_s
        )
        narration = " ".join(
            scene.script_text.strip() for scene in script.scenes if scene.script_text.strip()
        )
        sentences = self._estimate_sentence_timestamps(narration, total_duration)
        return {
            "total_duration": float(total_duration),
            "words_per_minute": WORDS_PER_MINUTE,
            "scene_pause_seconds": float(pause_s),
            "words": [w.model_dump() for w in words],
            "sentences": sentences,
            "scenes": scene_timings,
        }

    def _estimate_word_timestamps_with_pauses(
        self,
        script: VideoScript,
        speech_durations: list[float],
        *,
        pause_s: float,
    ) -> list[WordTimestamp]:
        """Place words inside each scene's speech span; skip inter-scene silence."""
        words: list[WordTimestamp] = []
        cursor = 0.0
        for index, (scene, speech) in enumerate(
            zip(script.scenes, speech_durations, strict=True)
        ):
            speech = max(0.05, float(speech))
            local = self._estimate_word_timestamps(scene.script_text or "", speech)
            for item in local:
                words.append(
                    WordTimestamp(
                        word=item.word,
                        start=cursor + float(item.start),
                        end=cursor + float(item.end),
                    )
                )
            cursor += speech
            if index < len(script.scenes) - 1:
                cursor += max(0.0, float(pause_s))
        return words

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_narration_text(
        script: VideoScript,
        *,
        use_per_scene_text: bool,
        scene_pause_join: bool = False,
    ) -> str:
        if use_per_scene_text or not script.full_script.strip():
            parts = [scene.script_text.strip() for scene in script.scenes if scene.script_text.strip()]
            joiner = _SCENE_PAUSE_JOIN if scene_pause_join else " "
            return joiner.join(parts).strip()
        return script.full_script.strip()

    def _estimate_word_timestamps(self, text: str, duration: float) -> list[WordTimestamp]:
        """Distribute words across ``duration``, weighted by character length.

        Longer tokens receive slightly more airtime. The final word is clamped
        so ``end == duration``.
        """
        tokens = _WORD_RE.findall(text)
        if not tokens:
            return []

        weights = [max(1, len(re.sub(r"[^\w]", "", tok))) for tok in tokens]
        total_weight = float(sum(weights)) or float(len(weights))
        cursor = 0.0
        words: list[WordTimestamp] = []

        for token, weight in zip(tokens, weights, strict=True):
            span = duration * (weight / total_weight)
            start = cursor
            end = min(duration, cursor + span)
            # Guarantee a tiny positive span for ZW / punctuation-only edge cases.
            if end <= start:
                end = min(duration, start + 0.01)
            words.append(WordTimestamp(word=token, start=start, end=end))
            cursor = end

        if words:
            words[-1] = words[-1].model_copy(update={"end": float(duration)})
        return words

    def _build_timing_dictionary(
        self,
        script: VideoScript,
        words: list[WordTimestamp],
        total_duration: float,
    ) -> dict[str, Any]:
        """Build a serializable timing dict (word + sentence + per-scene)."""
        sentences = self._estimate_sentence_timestamps(
            self._resolve_narration_text(script, use_per_scene_text=False),
            total_duration,
        )
        scene_timings = self._allocate_scene_timings(script, words, total_duration)

        return {
            "total_duration": total_duration,
            "words_per_minute": WORDS_PER_MINUTE,
            "words": [w.model_dump() for w in words],
            "sentences": sentences,
            "scenes": scene_timings,
        }

    def _allocate_scene_timings(
        self,
        script: VideoScript,
        words: list[WordTimestamp],
        total_duration: float,
    ) -> list[dict[str, Any]]:
        """Map contiguous word spans onto each scene based on script_text length."""
        if not script.scenes:
            return []

        # Prefer proportional allocation by scene word counts so we don't depend
        # on exact string equality between full_script and concatenated scenes.
        word_counts = [max(1, len(_WORD_RE.findall(scene.script_text))) for scene in script.scenes]
        total_words = float(sum(word_counts))
        raw_durations = [total_duration * (count / total_words) for count in word_counts]

        # Correct floating-point drift so the sum matches total_duration exactly.
        drift = total_duration - sum(raw_durations)
        raw_durations[-1] = max(0.05, raw_durations[-1] + drift)

        cursor = 0.0
        scene_timings: list[dict[str, Any]] = []
        word_cursor = 0

        for scene, duration, count in zip(script.scenes, raw_durations, word_counts, strict=True):
            start = cursor
            end = cursor + duration
            scene_words = words[word_cursor : word_cursor + count]
            word_cursor += count
            if scene_words:
                # Prefer real word boundaries when available.
                start = scene_words[0].start
                end = scene_words[-1].end
            scene_timings.append(
                {
                    "scene_id": scene.scene_id,
                    "start": float(start),
                    "end": float(end),
                    "duration": float(max(0.05, end - start)),
                    "word_count": count,
                }
            )
            cursor = end

        # Force the final scene to land on the audio end.
        if scene_timings:
            scene_timings[-1]["end"] = float(total_duration)
            scene_timings[-1]["duration"] = float(
                max(0.05, total_duration - scene_timings[-1]["start"])
            )
        return scene_timings

    @staticmethod
    def _estimate_sentence_timestamps(text: str, duration: float) -> list[dict[str, Any]]:
        parts = [part.strip() for part in _SENTENCE_RE.split(text) if part and part.strip()]
        if not parts:
            return [{"index": 0, "text": text, "start": 0.0, "end": duration}]

        weights = [max(1, len(_WORD_RE.findall(part))) for part in parts]
        total_weight = float(sum(weights)) or float(len(weights))
        cursor = 0.0
        sentences: list[dict[str, Any]] = []
        for idx, (part, weight) in enumerate(zip(parts, weights, strict=True)):
            span = duration * (weight / total_weight)
            start = cursor
            end = duration if idx == len(parts) - 1 else min(duration, cursor + span)
            sentences.append(
                {
                    "index": idx,
                    "text": part,
                    "start": float(start),
                    "end": float(end),
                }
            )
            cursor = end
        return sentences

    def _apply_scene_durations(
        self,
        script: VideoScript,
        timing: dict[str, Any],
        total_duration: float,
    ) -> VideoScript:
        by_id = {item["scene_id"]: item for item in timing.get("scenes", [])}
        updated_scenes: list[SceneData] = []

        for scene in script.scenes:
            item = by_id.get(scene.scene_id)
            if item:
                duration = float(item["duration"])
            else:
                # Fallback: proportional WPM estimate for this scene alone.
                duration = self.estimate_duration_wpm(scene.script_text)
            updated_scenes.append(scene.model_copy(update={"duration": max(0.05, duration)}))

        # Final normalization pass so scene durations sum to probed audio length.
        current_total = sum(s.duration for s in updated_scenes)
        if current_total > 0 and not math.isclose(current_total, total_duration, rel_tol=0.0, abs_tol=0.05):
            scale = total_duration / current_total
            updated_scenes = [
                s.model_copy(update={"duration": max(0.05, s.duration * scale)})
                for s in updated_scenes
            ]
            # Absorb residual into the last scene.
            residual = total_duration - sum(s.duration for s in updated_scenes)
            last = updated_scenes[-1]
            updated_scenes[-1] = last.model_copy(
                update={"duration": max(0.05, last.duration + residual)}
            )

        return script.model_copy(update={"scenes": updated_scenes})

    # ------------------------------------------------------------------
    # Duration probing
    # ------------------------------------------------------------------

    def _probe_duration_seconds(self, path: Path) -> float:
        """Best-effort duration probe (wav header → MoviePy/ffprobe → bitrate)."""
        suffix = path.suffix.lower()
        if suffix == ".wav":
            try:
                return self._wav_duration(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("WAV probe failed for %s: %s", path, exc)

        try:
            from moviepy import AudioFileClip

            clip = AudioFileClip(str(path))
            try:
                probed = float(clip.duration or 0.0)
            finally:
                clip.close()
            if probed > 0:
                return probed
        except Exception as exc:  # noqa: BLE001
            logger.warning("moviepy duration probe failed for %s: %s", path, exc)

        # Rough MP3 estimate assuming ~128 kbps CBR.
        try:
            size_bytes = path.stat().st_size
            estimate = (size_bytes * 8) / 128_000
            if estimate > 0:
                return estimate
        except OSError as exc:
            logger.warning("Bitrate estimate failed for %s: %s", path, exc)

        return 0.0

    @staticmethod
    def _wav_duration(path: Path) -> float:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate) if rate else 0.0
