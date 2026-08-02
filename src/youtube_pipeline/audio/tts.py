"""Text-to-speech providers (OpenAI / ElevenLabs) with scene duration timing."""

from __future__ import annotations

import math
import re
import wave
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import Settings, TTSProvider, get_settings
from youtube_pipeline.exceptions import AudioGenerationError, ConfigurationError
from youtube_pipeline.models import SceneData, VideoScript, WordTimestamp
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

# Average conversational narration rate used when forced alignment is unavailable.
WORDS_PER_MINUTE = 150.0
SECONDS_PER_WORD = 60.0 / WORDS_PER_MINUTE  # 0.4s

_WORD_RE = re.compile(r"\S+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


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
            if not self.settings.elevenlabs_voice_id:
                raise ConfigurationError(
                    "ELEVENLABS_VOICE_ID is required for TTS provider 'elevenlabs'"
                )
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

        text = self._resolve_narration_text(script, use_per_scene_text=use_per_scene_text)
        if not text.strip():
            raise AudioGenerationError("Cannot synthesize empty narration text")

        logger.info(
            "Synthesizing voiceover | provider=%s | chars=%d",
            self.settings.tts_provider.value,
            len(text),
        )

        try:
            if self.settings.tts_provider == TTSProvider.OPENAI:
                self._synthesize_openai(text, audio_path, voice=voice)
            elif self.settings.tts_provider == TTSProvider.ELEVENLABS:
                self._synthesize_elevenlabs(text, audio_path, voice=voice)
            elif self.settings.tts_provider == TTSProvider.GTTS:
                self._synthesize_gtts(text, audio_path, voice=voice)
            elif self.settings.tts_provider == TTSProvider.EDGE_TTS:
                self._synthesize_edge_tts(text, audio_path, voice=voice)
            else:
                raise ConfigurationError(
                    f"Unsupported TTS provider: {self.settings.tts_provider!r}"
                )
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
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

        client = ElevenLabs(api_key=self.settings.elevenlabs_api_key)
        voice_id = voice or self.settings.elevenlabs_voice_id
        if not voice_id:
            raise ConfigurationError("ElevenLabs voice id is missing")

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

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _synthesize_edge_tts(self, text: str, output_path: Path, *, voice: str | None) -> None:
        """Synthesize speech with Microsoft Edge neural TTS (keyless).

        ``voice`` overrides ``settings.edge_tts_voice`` (e.g. ``en-US-JennyNeural``).
        """
        import asyncio

        import edge_tts

        selected_voice = (voice or self.settings.edge_tts_voice or "en-US-AriaNeural").strip()
        rate = str(getattr(self.settings, "edge_tts_rate", None) or "-8%").strip()
        pitch = str(getattr(self.settings, "edge_tts_pitch", None) or "+2Hz").strip()
        volume = str(getattr(self.settings, "edge_tts_volume", None) or "+0%").strip()
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

        try:
            asyncio.run(_run())
        except RuntimeError as exc:
            # Fallback if already inside a running event loop (rare for CLI).
            if "asyncio.run()" not in str(exc) and "running event loop" not in str(exc).lower():
                raise
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_narration_text(script: VideoScript, *, use_per_scene_text: bool) -> str:
        if use_per_scene_text or not script.full_script.strip():
            return " ".join(scene.script_text.strip() for scene in script.scenes).strip()
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
