import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  ASPECT_OPTIONS,
  FALLBACK_LANGUAGES,
  LANGUAGE_DEFAULT_VOICES,
  STYLE_OPTIONS,
  generateVideo,
  listLanguages,
} from "../api/client";
import type {
  AspectRatio,
  LanguageOption,
  QuizMode,
  VideoFormat,
  VideoStyle,
} from "../api/types";
import { VoicePicker } from "./VoicePicker";

function defaultDuration(
  format: VideoFormat,
  aspect: AspectRatio,
  quizMode: QuizMode,
  questionCount: number,
) {
  if (format === "dialogue") return 75;
  if (format === "quizverse") {
    return quizMode === "comment" ? 30 : Math.max(60, questionCount * 20 + 10);
  }
  return aspect === "9:16" ? 45 : 90;
}

export function GenerateForm() {
  const navigate = useNavigate();
  const [idea, setIdea] = useState("");
  const [language, setLanguage] = useState("en");
  const [languages, setLanguages] = useState<LanguageOption[]>(FALLBACK_LANGUAGES);
  const [style, setStyle] = useState<VideoStyle>("cinematic");
  const [aspect, setAspect] = useState<AspectRatio>("16:9");
  const [format, setFormat] = useState<VideoFormat>("narrative");
  const [quizMode, setQuizMode] = useState<QuizMode>("comment");
  const [questionCount, setQuestionCount] = useState(1);
  const [duration, setDuration] = useState(90);
  const [durationEdited, setDurationEdited] = useState(false);
  const [locale, setLocale] = useState("en");
  const [voice, setVoice] = useState(LANGUAGE_DEFAULT_VOICES.en);
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState("We’ll work in the background — you can leave this tab open.");

  useEffect(() => {
    listLanguages()
      .then((langs) => {
        if (langs.length) setLanguages(langs);
      })
      .catch(() => undefined);
  }, []);

  function onLanguageChange(code: string) {
    setLanguage(code);
    setLocale(code);
    setVoice(LANGUAGE_DEFAULT_VOICES[code] || LANGUAGE_DEFAULT_VOICES.en);
    setHint(`Script language set to ${code}. Matching Edge-TTS voices loaded.`);
  }

  function onFormatChange(nextFormat: VideoFormat) {
    setFormat(nextFormat);
    let nextAspect = aspect;
    if (nextFormat === "quizverse") {
      nextAspect = quizMode === "comment" ? "9:16" : "16:9";
      setAspect(nextAspect);
    } else if (nextFormat === "dialogue") {
      nextAspect = "9:16";
      setAspect(nextAspect);
    }
    if (!durationEdited) {
      setDuration(defaultDuration(nextFormat, nextAspect, quizMode, questionCount));
    }
  }

  function onQuizModeChange(nextMode: QuizMode) {
    setQuizMode(nextMode);
    const nextAspect = nextMode === "comment" ? "9:16" : "16:9";
    const nextQuestionCount = nextMode === "comment" ? 1 : 5;
    setAspect(nextAspect);
    setQuestionCount(nextQuestionCount);
    if (!durationEdited) {
      setDuration(defaultDuration("quizverse", nextAspect, nextMode, nextQuestionCount));
    }
  }

  function onAspectChange(nextAspect: AspectRatio) {
    setAspect(nextAspect);
    if (!durationEdited) {
      setDuration(defaultDuration(format, nextAspect, quizMode, questionCount));
    }
  }

  function onQuestionCountChange(nextQuestionCount: number) {
    setQuestionCount(nextQuestionCount);
    if (!durationEdited) {
      setDuration(defaultDuration(format, aspect, quizMode, nextQuestionCount));
    }
  }

  function onDurationChange(nextDuration: number) {
    setDuration(nextDuration);
    setDurationEdited(true);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = idea.trim();
    if (trimmed.length < 3) {
      setHint("Please enter a longer idea (at least 3 characters).");
      return;
    }
    setBusy(true);
    setHint("Submitting job…");
    try {
      const accepted = await generateVideo({
        idea: trimmed,
        style,
        aspect_ratio: aspect,
        duration,
        language,
        voice: voice || LANGUAGE_DEFAULT_VOICES[language] || LANGUAGE_DEFAULT_VOICES.en,
        format,
        ...(format === "quizverse"
          ? { quiz_mode: quizMode, question_count: questionCount }
          : {}),
      });
      setHint("Writing your story and recording the voice…");
      navigate(`/studio/${accepted.job_id}`);
    } catch (err) {
      setBusy(false);
      setHint(err instanceof Error ? err.message : "Could not start generation.");
    }
  }

  return (
    <form className="compose-form" onSubmit={onSubmit} noValidate>
      <label className="field idea-field">
        <span>Your idea</span>
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={3}
          required
          minLength={3}
          placeholder="e.g. The Matsya Avatar and Manu’s ancient wooden ark"
        />
      </label>

      <div className="field-grid">
        <label className="field">
          <span>Format</span>
          <select
            value={format}
            onChange={(e) => onFormatChange(e.target.value as VideoFormat)}
          >
            <option value="narrative">Narrative</option>
            <option value="quizverse">Quizverse</option>
            <option value="dialogue">Dialogue</option>
          </select>
        </label>

        {format === "quizverse" ? (
          <>
            <label className="field">
              <span>Quiz mode</span>
              <select
                value={quizMode}
                onChange={(e) => onQuizModeChange(e.target.value as QuizMode)}
              >
                <option value="comment">Comment</option>
                <option value="reveal">Reveal</option>
              </select>
            </label>
            <label className="field">
              <span>Question count</span>
              <input
                type="number"
                min={1}
                max={quizMode === "comment" ? 5 : 15}
                value={questionCount}
                onChange={(e) => onQuestionCountChange(Number(e.target.value))}
                required
              />
            </label>
          </>
        ) : null}
      </div>

      <div className="field-grid">
        <label className="field">
          <span>Language</span>
          <select value={language} onChange={(e) => onLanguageChange(e.target.value)}>
            {languages.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.native_name && lang.native_name !== lang.name
                  ? `${lang.name} (${lang.native_name})`
                  : lang.name}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Style</span>
          <select value={style} onChange={(e) => setStyle(e.target.value as VideoStyle)}>
            {STYLE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Aspect ratio</span>
          <select
            value={aspect}
            onChange={(e) => onAspectChange(e.target.value as AspectRatio)}
          >
            {ASPECT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Duration (seconds)</span>
          <input
            type="number"
            min={1}
            value={duration}
            onChange={(e) => onDurationChange(Number(e.target.value))}
            required
          />
        </label>

      </div>

      <VoicePicker
        locale={locale}
        voice={voice}
        preferredVoice={LANGUAGE_DEFAULT_VOICES[language]}
        onLocaleChange={setLocale}
        onVoiceChange={setVoice}
        onStatus={setHint}
      />

      <div className="form-actions">
        <button type="submit" className="cta" disabled={busy}>
          {busy ? "Generating…" : "Generate video"}
        </button>
        <p className="hint">{hint}</p>
      </div>
    </form>
  );
}
