import { useEffect, useRef, useState } from "react";
import {
  LANGUAGE_DEFAULT_VOICES,
  LOCALE_OPTIONS,
  listVoices,
  previewVoice,
} from "../api/client";
import type { VoiceOption } from "../api/types";

type Props = {
  locale: string;
  voice: string;
  onLocaleChange: (locale: string) => void;
  onVoiceChange: (voice: string) => void;
  preferredVoice?: string;
  onStatus?: (msg: string) => void;
  compact?: boolean;
};

export function VoicePicker({
  locale,
  voice,
  onLocaleChange,
  onVoiceChange,
  preferredVoice,
  onStatus,
  compact,
}: Props) {
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const data = await listVoices(locale);
        if (cancelled) return;
        setVoices(data.voices || []);
        const prefer =
          preferredVoice ||
          voice ||
          LANGUAGE_DEFAULT_VOICES[locale] ||
          data.default_voice;
        const ids = new Set((data.voices || []).map((v) => v.id));
        if (prefer && ids.has(prefer)) {
          onVoiceChange(prefer);
        } else if (data.default_voice && ids.has(data.default_voice)) {
          onVoiceChange(data.default_voice);
        } else if (data.voices?.[0]) {
          onVoiceChange(data.voices[0].id);
        }
      } catch (err) {
        onStatus?.(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, preferredVoice]);

  async function onPreview() {
    if (!voice) return;
    setPreviewing(true);
    onStatus?.(`Generating sample for ${voice}…`);
    try {
      const data = await previewVoice(voice);
      if (audioRef.current) {
        audioRef.current.hidden = false;
        audioRef.current.src = data.preview_url;
        await audioRef.current.play().catch(() => undefined);
      }
      onStatus?.(data.message || `Preview ready: ${voice}`);
    } catch (err) {
      onStatus?.(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <div className={compact ? "voice-row" : "voice-row"}>
      <label className="field">
        <span>Voice locale</span>
        <select value={locale} onChange={(e) => onLocaleChange(e.target.value)}>
          {LOCALE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Voice</span>
        <select
          value={voice}
          onChange={(e) => onVoiceChange(e.target.value)}
          disabled={loading || voices.length === 0}
        >
          {voices.length === 0 ? (
            <option value={voice || ""}>{voice || "Loading voices…"}</option>
          ) : (
            voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label || v.id}
              </option>
            ))
          )}
        </select>
      </label>
      <div>
        <button
          type="button"
          className="cta secondary"
          onClick={onPreview}
          disabled={!voice || previewing}
        >
          {previewing ? "Previewing…" : "Preview voice"}
        </button>
        <audio ref={audioRef} controls preload="none" hidden className="audio-player" />
      </div>
    </div>
  );
}
