"""Text-to-speech generation with approximate word-level timestamps."""

from __future__ import annotations

import re
import wave
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import Settings, TTSProvider, get_settings
from youtube_pipeline.audio.subtitles import SubtitleWriter
from youtube_pipeline.exceptions import AudioGenerationError, ConfigurationError
from youtube_pipeline.models import AudioArtifact, ScriptPackage, WordTimestamp
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_WORD_RE = re.compile(r"\S+")


class AudioEngine:
    """Convert a script package into spoken audio + subtitle artifacts."""

    def __init__(
        self,
        settings: Settings | None = None,
        subtitle_writer: SubtitleWriter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.subtitle_writer = subtitle_writer or SubtitleWriter()
        self._validate_config()

    def _validate_config(self) -> None:
        if self.settings.tts_provider == TTSProvider.OPENAI and not self.settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for TTS provider 'openai'")
        if self.settings.tts_provider == TTSProvider.ELEVENLABS:
            if not self.settings.elevenlabs_api_key:
                raise ConfigurationError("ELEVENLABS_API_KEY is required for TTS provider 'elevenlabs'")
            if not self.settings.elevenlabs_voice_id:
                raise ConfigurationError("ELEVENLABS_VOICE_ID is required for TTS provider 'elevenlabs'")

    def synthesize(
        self,
        script: ScriptPackage,
        output_dir: Path,
        *,
        voice: str | None = None,
    ) -> AudioArtifact:
        """Generate voiceover audio, estimate word timings, and write subtitle files."""
        ensure_dir(output_dir)
        audio_path = output_dir / "voiceover.mp3"
        logger.info("Synthesizing voiceover | provider=%s", self.settings.tts_provider.value)

        try:
            if self.settings.tts_provider == TTSProvider.OPENAI:
                self._synthesize_openai(script.full_script, audio_path, voice=voice)
            else:
                self._synthesize_elevenlabs(script.full_script, audio_path, voice=voice)
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AudioGenerationError(f"TTS synthesis failed: {exc}") from exc

        duration = self._probe_duration_seconds(audio_path)
        if duration <= 0:
            raise AudioGenerationError(f"Invalid audio duration for {audio_path}")

        words = self._estimate_word_timestamps(script.full_script, duration)
        cues = self.subtitle_writer.build_cues(words)
        srt_path = self.subtitle_writer.write_srt(cues, output_dir / "captions.srt")
        vtt_path = self.subtitle_writer.write_vtt(cues, output_dir / "captions.vtt")

        artifact = AudioArtifact(
            audio_path=audio_path,
            duration_seconds=duration,
            word_timestamps=words,
            subtitle_cues=cues,
            srt_path=srt_path,
            vtt_path=vtt_path,
        )
        logger.info(
            "Audio ready | duration=%.2fs | cues=%d",
            artifact.duration_seconds,
            len(cues),
        )
        return artifact

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _synthesize_openai(self, text: str, output_path: Path, *, voice: str | None) -> None:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        with client.audio.speech.with_streaming_response.create(
            model=self.settings.openai_tts_model,
            voice=voice or self.settings.openai_tts_voice,
            input=text,
        ) as response:
            response.stream_to_file(output_path)

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _synthesize_elevenlabs(self, text: str, output_path: Path, *, voice: str | None) -> None:
        from elevenlabs import ElevenLabs

        client = ElevenLabs(api_key=self.settings.elevenlabs_api_key)
        voice_id = voice or self.settings.elevenlabs_voice_id
        assert voice_id is not None  # validated in _validate_config

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

    def _estimate_word_timestamps(self, text: str, duration: float) -> list[WordTimestamp]:
        """Distribute words evenly across audio duration as a practical baseline.

        Providers with forced alignment can replace this later without changing
        the orchestrator contract.
        """
        tokens = _WORD_RE.findall(text)
        if not tokens:
            return []

        # Weight slightly by character length so longer words get more airtime.
        weights = [max(1, len(re.sub(r"[^\w]", "", tok))) for tok in tokens]
        total_weight = float(sum(weights))
        cursor = 0.0
        words: list[WordTimestamp] = []
        for token, weight in zip(tokens, weights, strict=True):
            span = duration * (weight / total_weight)
            start = cursor
            end = min(duration, cursor + span)
            words.append(WordTimestamp(word=token, start=start, end=end))
            cursor = end
        if words:
            words[-1] = words[-1].model_copy(update={"end": duration})
        return words

    def _probe_duration_seconds(self, path: Path) -> float:
        """Best-effort duration probe without requiring ffprobe at import time."""
        suffix = path.suffix.lower()
        if suffix == ".wav":
            return self._wav_duration(path)

        # Prefer moviepy/ffprobe when available for mp3/m4a/etc.
        try:
            from moviepy import AudioFileClip

            clip = AudioFileClip(str(path))
            try:
                return float(clip.duration or 0.0)
            finally:
                clip.close()
        except Exception:  # noqa: BLE001
            logger.warning("moviepy duration probe failed; falling back to bitrate estimate")

        # Rough MP3 estimate assuming ~128 kbps
        size_bytes = path.stat().st_size
        return max(0.1, (size_bytes * 8) / 128_000)

    @staticmethod
    def _wav_duration(path: Path) -> float:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate) if rate else 0.0
