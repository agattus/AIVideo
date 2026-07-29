/** Plain-language status labels for the UI. */
export const STATUS_LABELS: Record<string, string> = {
  queued: "In line",
  processing: "Working",
  waiting_for_assets: "Your turn",
  completed: "Ready",
  failed: "Needs attention",
};

/** Rotating tips while Phase 1 (script + voice) is running. */
export const WRITING_TIPS = [
  "Shaping your story beat by beat…",
  "Finding a voice that fits the mood…",
  "Warming up the narrator…",
  "Sketching each scene in words first…",
  "Keeping the pacing tight and cinematic…",
  "Almost ready for your images…",
  "Good films start with a clear through-line…",
  "Polishing the cold open…",
];

/** Rotating tips while the final cut is assembling. */
export const ASSEMBLE_TIPS = [
  "Lining up your scenes…",
  "Adding gentle camera motion…",
  "Timing captions to the voice…",
  "Mixing narration and music…",
  "Putting the final cut together…",
  "Almost there — hang tight…",
];

/** Tips while waiting for the user to upload images. */
export const WAITING_TIPS = [
  "Copy a visual prompt, generate an image, then upload it here.",
  "You can replace any scene image before you assemble.",
  "Preview the voiceover and swap the music if you like.",
  "When every scene has an image, hit Assemble.",
];

/** Map leftover technical backend strings to plain language. */
const STAGE_REWRITES: Array<[RegExp, string]> = [
  [/stage\s*\d+\s*\/\s*\d+\s*:?\s*/i, ""],
  [/human[- ]in[- ]the[- ]loop/i, "your film"],
  [/synthesiz\w*\s+(edge[- ]?tts|tts).*/i, "Recording the narration…"],
  [/edge[- ]?tts/i, "voice"],
  [/generating script via.*/i, "Writing your story…"],
  [/exporting visual prompts.*/i, "Preparing scene prompts for your images…"],
  [/waiting for assets.*/i, "Your turn — add scene images, then assemble"],
  [/ingesting uploaded.*/i, "Checking your scene images…"],
  [/publishing final.*/i, "Finishing your film…"],
  [/completed\s*[—-].*/i, "Your film is ready"],
  [/queued\s*[—-].*/i, "Getting started on your film…"],
  [/ffmpeg|moviepy|celery|redis|llm|groq|openai|anthropic/i, ""],
];

export function friendlyStatus(status: string): string {
  return STATUS_LABELS[status] || status.replace(/_/g, " ");
}

export function friendlyStage(raw?: string | null): string {
  if (!raw) return "Getting ready…";
  let text = String(raw).trim();
  for (const [pattern, replacement] of STAGE_REWRITES) {
    text = text.replace(pattern, replacement).trim();
  }
  // Collapse leftover punctuation / whitespace from rewrites.
  text = text.replace(/\s{2,}/g, " ").replace(/^[:\-–—]\s*/, "").trim();
  if (!text) return "Working on your film…";
  // Ensure sentence-like ending for short phrases.
  if (!/[.!?…]$/.test(text) && text.length < 80) {
    // Keep as-is; many of our messages already use ellipsis.
  }
  return text;
}

export function tipsForStatus(status: string, percent: number): string[] {
  if (status === "waiting_for_assets") return WAITING_TIPS;
  if (status === "completed" || status === "failed") return [];
  if (status === "processing" && percent >= 80) return ASSEMBLE_TIPS;
  if (status === "queued" || status === "processing") return WRITING_TIPS;
  return WRITING_TIPS;
}

export function pickTip(tips: string[], tick: number): string | null {
  if (!tips.length) return null;
  return tips[Math.abs(tick) % tips.length] || null;
}
