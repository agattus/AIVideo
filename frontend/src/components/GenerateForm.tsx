import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  ASPECT_OPTIONS,
  CONTENT_TYPE_OPTIONS,
  FALLBACK_LANGUAGES,
  FORM_LENGTH_OPTIONS,
  FORM_PRESETS,
  LANGUAGE_DEFAULT_VOICES,
  STYLE_OPTIONS,
  generateVideo,
  listLanguages,
} from "../api/client";
import type {
  AspectRatio,
  ContentType,
  FormLength,
  LanguageOption,
  VideoStyle,
} from "../api/types";
import { VoicePicker } from "./VoicePicker";

function presetKey(contentType: ContentType, formLength: FormLength) {
  return `${contentType}:${formLength}`;
}

export function GenerateForm() {
  const navigate = useNavigate();
  const [idea, setIdea] = useState("");
  const [contentType, setContentType] = useState<ContentType>("narration");
  const [formLength, setFormLength] = useState<FormLength>("short");
  const [language, setLanguage] = useState("en");
  const [languages, setLanguages] = useState<LanguageOption[]>(FALLBACK_LANGUAGES);
  const [style, setStyle] = useState<VideoStyle>("fast_paced_shorts");
  const [aspect, setAspect] = useState<AspectRatio>("9:16");
  const [duration, setDuration] = useState(45);
  const [maxScenes, setMaxScenes] = useState(6);
  const [holdSeconds, setHoldSeconds] = useState(10);
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

  function applyPreset(nextType: ContentType, nextLength: FormLength) {
    const preset = FORM_PRESETS[presetKey(nextType, nextLength)];
    if (!preset) return;
    setStyle(preset.style);
    setAspect(preset.aspect_ratio);
    setDuration(preset.duration);
    setMaxScenes(preset.max_scenes);
    if (preset.hold_seconds) setHoldSeconds(preset.hold_seconds);
  }

  function onContentTypeChange(next: ContentType) {
    setContentType(next);
    applyPreset(next, formLength);
    setHint(
      next === "quiz"
        ? "Quiz mode — viewers see a question, wait, then get the answer."
        : "Narration mode — classic scripted film with voiceover.",
    );
  }

  function onFormLengthChange(next: FormLength) {
    setFormLength(next);
    applyPreset(contentType, next);
    setHint(next === "short" ? "Short form preset applied." : "Long form preset applied.");
  }

  function onLanguageChange(code: string) {
    setLanguage(code);
    setLocale(code);
    setVoice(LANGUAGE_DEFAULT_VOICES[code] || LANGUAGE_DEFAULT_VOICES.en);
    setHint(`Script language set to ${code}. Matching Edge-TTS voices loaded.`);
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
        content_type: contentType,
        form_length: formLength,
        style,
        aspect_ratio: aspect,
        duration,
        max_scenes: maxScenes,
        hold_seconds: contentType === "quiz" ? holdSeconds : undefined,
        language,
        voice: voice || LANGUAGE_DEFAULT_VOICES[language] || LANGUAGE_DEFAULT_VOICES.en,
      });
      setHint(
        contentType === "quiz"
          ? "Writing quiz questions and recording the host…"
          : "Writing your story and recording the voice…",
      );
      navigate(`/studio/${accepted.job_id}`);
    } catch (err) {
      setBusy(false);
      setHint(err instanceof Error ? err.message : "Could not start generation.");
    }
  }

  const ideaPlaceholder =
    contentType === "quiz"
      ? "e.g. Solar system trivia for teens"
      : "e.g. The Matsya Avatar and Manu’s ancient wooden ark";

  return (
    <form className="compose-form" onSubmit={onSubmit} noValidate>
      <div className="choice-grid" role="group" aria-label="Content type">
        {CONTENT_TYPE_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`choice-tile${contentType === opt.value ? " active" : ""}`}
            onClick={() => onContentTypeChange(opt.value)}
          >
            <strong>{opt.label}</strong>
            <span>{opt.blurb}</span>
          </button>
        ))}
      </div>

      <div className="choice-grid compact" role="group" aria-label="Form length">
        {FORM_LENGTH_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`choice-tile${formLength === opt.value ? " active" : ""}`}
            onClick={() => onFormLengthChange(opt.value)}
          >
            <strong>{opt.label}</strong>
            <span>{opt.blurb}</span>
          </button>
        ))}
      </div>

      <label className="field idea-field">
        <span>{contentType === "quiz" ? "Quiz topic" : "Your idea"}</span>
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={3}
          required
          minLength={3}
          placeholder={ideaPlaceholder}
        />
      </label>

      <div className={`field-grid ${contentType === "quiz" ? "six" : "five"}`}>
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
          <select value={aspect} onChange={(e) => setAspect(e.target.value as AspectRatio)}>
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
            min={15}
            max={3600}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            required
          />
        </label>

        <label className="field">
          <span>{contentType === "quiz" ? "Scenes (Q+A pairs)" : "Max scenes"}</span>
          <input
            type="number"
            min={2}
            max={240}
            step={contentType === "quiz" ? 2 : 1}
            value={maxScenes}
            onChange={(e) => setMaxScenes(Number(e.target.value))}
            required
          />
        </label>

        {contentType === "quiz" ? (
          <label className="field">
            <span>Think-time (seconds)</span>
            <input
              type="number"
              min={3}
              max={30}
              value={holdSeconds}
              onChange={(e) => setHoldSeconds(Number(e.target.value))}
              required
            />
          </label>
        ) : null}
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
          {busy
            ? "Generating…"
            : contentType === "quiz"
              ? "Generate quiz"
              : "Generate video"}
        </button>
        <p className="hint">{hint}</p>
      </div>
    </form>
  );
}
