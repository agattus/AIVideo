import type {
  GenerateAccepted,
  GeneratePayload,
  JobStatusResponse,
  JobSummary,
  LanguageOption,
  VoiceListResponse,
  WorkspaceResponse,
} from "./types";

async function parseError(res: Response): Promise<string> {
  const detail = await res.json().catch(() => ({} as { detail?: string }));
  if (typeof detail.detail === "string") return detail.detail;
  return `Request failed (${res.status})`;
}

/** Normalize API language rows (`id`/`label`) to UI shape (`code`/`name`). */
export function normalizeLanguageOptions(raw: unknown[]): LanguageOption[] {
  const out: LanguageOption[] = [];
  for (const item of raw || []) {
    const row = (item || {}) as Record<string, unknown>;
    const code = String(row.code ?? row.id ?? "").trim();
    if (!code) continue;
    const name = String(row.name ?? row.label ?? code);
    const native_name =
      row.native_name != null
        ? String(row.native_name)
        : row.native_label != null
          ? String(row.native_label)
          : undefined;
    const default_voice =
      row.default_voice != null ? String(row.default_voice) : undefined;
    out.push({ code, name, native_name, default_voice });
  }
  return out;
}

export async function listLanguages(): Promise<LanguageOption[]> {
  const res = await fetch("/api/v1/languages");
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return normalizeLanguageOptions(data.languages || []);
}

export async function listVoices(locale: string): Promise<VoiceListResponse> {
  const res = await fetch(`/api/v1/voices?locale=${encodeURIComponent(locale)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function previewVoice(voice: string): Promise<{ preview_url: string; message?: string }> {
  const res = await fetch("/api/v1/voices/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function generateVideo(payload: GeneratePayload): Promise<GenerateAccepted> {
  const res = await fetch("/api/v1/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`/api/v1/status/${encodeURIComponent(jobId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getWorkspace(jobId: string): Promise<WorkspaceResponse> {
  const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/workspace`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function generateSceneImage(jobId: string, sceneId: number) {
  const res = await fetch(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/scenes/${encodeURIComponent(sceneId)}/generate`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function generateMissingImages(jobId: string, force = false) {
  const query = force ? "?force=true" : "";
  const res = await fetch(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/generate-images${query}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listJobs(limit = 40): Promise<JobSummary[]> {
  const res = await fetch(`/api/v1/jobs?limit=${limit}`);
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return data.jobs || [];
}

export async function reopenJob(jobId: string): Promise<{ message?: string }> {
  const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/reopen`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function uploadScene(jobId: string, sceneId: number, file: File) {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/scenes/${encodeURIComponent(sceneId)}`,
    { method: "POST", body },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function uploadAssetsZip(jobId: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/upload-assets?assemble=false`,
    { method: "POST", body },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function updateVoiceover(
  jobId: string,
  opts: { voice?: string; file?: File },
) {
  const body = new FormData();
  if (opts.file) body.append("file", opts.file);
  if (opts.voice) body.append("voice", opts.voice);
  const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/voiceover`, {
    method: "POST",
    body,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function updateBgm(jobId: string, opts: { style?: string; file?: File }) {
  const body = new FormData();
  if (opts.file) body.append("file", opts.file);
  if (opts.style) body.append("style", opts.style);
  const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/bgm`, {
    method: "POST",
    body,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function assembleVideo(jobId: string) {
  const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/assemble`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

export const LANGUAGE_DEFAULT_VOICES: Record<string, string> = {
  en: "en-US-ChristopherNeural",
  te: "te-IN-MohanNeural",
  hi: "hi-IN-MadhurNeural",
  ta: "ta-IN-ValluvarNeural",
  kn: "kn-IN-GaganNeural",
  ml: "ml-IN-MidhunNeural",
  bn: "bn-IN-BashkarNeural",
  gu: "gu-IN-NiranjanNeural",
  mr: "mr-IN-ManoharNeural",
  es: "es-ES-AlvaroNeural",
  fr: "fr-FR-HenriNeural",
  de: "de-DE-ConradNeural",
};

export const LOCALE_OPTIONS = [
  { value: "en", label: "English (all)" },
  { value: "te", label: "Telugu" },
  { value: "hi", label: "Hindi" },
  { value: "ta", label: "Tamil" },
  { value: "kn", label: "Kannada" },
  { value: "ml", label: "Malayalam" },
  { value: "bn", label: "Bengali" },
  { value: "gu", label: "Gujarati" },
  { value: "mr", label: "Marathi" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
  { value: "en-IN", label: "English (IN)" },
  { value: "all", label: "All languages" },
] as const;

export const STYLE_OPTIONS = [
  { value: "cinematic", label: "Cinematic" },
  { value: "documentary", label: "Documentary" },
  { value: "corporate", label: "Corporate" },
  { value: "fast_paced_shorts", label: "Fast-paced shorts" },
  { value: "animated", label: "Animated" },
  { value: "minimal", label: "Minimal" },
] as const;

export const BGM_STYLE_OPTIONS = [
  ...STYLE_OPTIONS,
  { value: "suspense", label: "Suspense" },
] as const;

export const ASPECT_OPTIONS = [
  { value: "16:9", label: "16:9 YouTube" },
  { value: "9:16", label: "9:16 Shorts / Reels" },
  { value: "1:1", label: "1:1 Square" },
] as const;

export const FALLBACK_LANGUAGES = [
  { code: "en", name: "English", native_name: "English" },
  { code: "te", name: "Telugu", native_name: "తెలుగు" },
  { code: "hi", name: "Hindi", native_name: "हिन्दी" },
  { code: "ta", name: "Tamil", native_name: "தமிழ்" },
  { code: "kn", name: "Kannada", native_name: "ಕನ್ನಡ" },
  { code: "ml", name: "Malayalam", native_name: "മലയാളം" },
  { code: "bn", name: "Bengali", native_name: "বাংলা" },
  { code: "gu", name: "Gujarati", native_name: "ગુજરાતી" },
  { code: "mr", name: "Marathi", native_name: "मराठी" },
  { code: "es", name: "Spanish", native_name: "Español" },
  { code: "fr", name: "French", native_name: "Français" },
  { code: "de", name: "German", native_name: "Deutsch" },
];
