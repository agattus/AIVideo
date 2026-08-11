import { useMemo, useState } from "react";
import { copyText, regenerateYoutubePack } from "../api/client";
import type { YoutubePack } from "../api/types";
import type { YtReachStepId } from "../lib/youtubeReachProgress";
import { YT_REACH_STEP_IDS } from "../lib/youtubeReachProgress";

type Step = {
  id: YtReachStepId;
  title: string;
  body: string;
  pipeline: string;
  tip?: string;
};

type Props = {
  jobId?: string;
  filmTitle: string;
  idea?: string;
  style?: string;
  aspectRatio?: string;
  pack?: YoutubePack | null;
  autoDone: Record<YtReachStepId, boolean>;
  onStatus?: (message: string) => void;
  onPackUpdated?: (pack: YoutubePack) => void;
};

function buildSteps(filmTitle: string, idea: string, style: string, aspect: string): Step[] {
  const short = filmTitle.length > 70 ? `${filmTitle.slice(0, 67)}…` : filmTitle;
  const topic = idea || filmTitle || "this story";
  const formatHint =
    aspect === "9:16"
      ? "Upload as a Short + a horizontal cut if you can — Shorts feed discovery first."
      : aspect === "1:1"
        ? "Square works in feeds; also export a 16:9 version for the main upload."
        : "Use 16:9 for the main upload; clip a 9:16 teaser for Shorts.";

  return [
    {
      id: "hook",
      title: "1. Lock a 3-second hook",
      pipeline: "Ticks when script is written (cold open)",
      body: `Pipeline forces a cold-open hook in scene 1. For “${short}”, viewers should feel mystery in under 3 seconds.`,
      tip: "Auto from Generate → Writing your story.",
    },
    {
      id: "title",
      title: "2. Search + curiosity title",
      pipeline: "Ticks when the SEO pack title exists",
      body: `Primary title is generated for YouTube curiosity. Pattern: concrete noun + tension — e.g. “${short}”.`,
      tip: "Auto from YouTube SEO pack.",
    },
    {
      id: "thumb",
      title: "3. High-contrast thumbnail still",
      pipeline: "Ticks when the first scene image is ready",
      body: "Use your strongest scene still as the thumb base — one subject, high contrast. Add 3–5 words of text in YouTube Studio.",
      tip: "Auto when scene images start landing.",
    },
    {
      id: "desc",
      title: "4. Description pack (hook → story → CTA)",
      pipeline: "Ticks when the SEO description pack is ready",
      body: "Copy the description draft below into YouTube. First lines = hook + keyword; then synopsis + comment CTA.",
      tip: "Auto after Phase 1 (script + TTS + SEO pack).",
    },
    {
      id: "packaging",
      title: "5. Tags / prompts / asset pack",
      pipeline: "Ticks when scene images (or prompts) are ready",
      body: `Tags + visual pack ready for “${topic}” (${style || "cinematic"}). ${formatHint}`,
      tip: "Auto when all scenes have images (or prompts pack exists).",
    },
    {
      id: "end",
      title: "6. Ending locked for end screen",
      pipeline: "Ticks when the final MP4 is assembled",
      body: "Final cut includes a lingering last beat — in YouTube Studio, add End screen (next video + subscribe) on the last 20s.",
      tip: "Auto after Assemble completes.",
    },
    {
      id: "timing",
      title: "7. Schedule pack ready",
      pipeline: "Ticks when the film file is ready to upload",
      body: "Film is downloadable. Schedule in YouTube when your audience is online (Analytics → Audience).",
      tip: "Auto when video.mp4 is published to Studio.",
    },
    {
      id: "firsthour",
      title: "8. First-hour share kit ready",
      pipeline: "Ticks when the film file is ready",
      body: "Share link + pinned question ready. Post to one niche community and reply to early comments in the first hour.",
      tip: "Auto when video is ready — you still do the sharing.",
    },
    {
      id: "retention",
      title: "9. Retention-minded cut ready",
      pipeline: "Ticks when the assembled cut exists",
      body: "Short scenes + motion + captions are baked for retention. After 48h, check Audience retention and tighten future films where the graph drops.",
      tip: "Auto after assemble.",
    },
    {
      id: "series",
      title: "10. Series sequel seed ready",
      pipeline: "Ticks when the film file is ready",
      body: `“${short}” is packaged to spawn a follow-up. Next Generate: “What happened after ${short}” or Part 2 with the same thumbnail style.`,
      tip: "Auto when video is ready — generate the sequel next.",
    },
  ];
}

function formatChapters(pack: YoutubePack): string {
  return (pack.chapters || [])
    .map((c) => {
      const total = Math.max(0, Number(c.start_seconds) || 0);
      const m = Math.floor(total / 60);
      const s = total % 60;
      return `${m}:${String(s).padStart(2, "0")} ${c.label}`;
    })
    .join("\n");
}

export function YouTubeReachGuide({
  jobId,
  filmTitle,
  idea = "",
  style = "",
  aspectRatio = "16:9",
  pack = null,
  autoDone,
  onStatus,
  onPackUpdated,
}: Props) {
  const [busy, setBusy] = useState(false);
  const steps = useMemo(
    () => buildSteps(filmTitle || "Untitled film", idea, style, aspectRatio),
    [filmTitle, idea, style, aspectRatio],
  );

  const completed = YT_REACH_STEP_IDS.filter((id) => autoDone[id]).length;

  const titleIdea = pack?.primary_title || filmTitle || "Untitled film";
  const descriptionIdea =
    pack?.description ||
    [
      `${filmTitle || "this film"} — watch till the end.`,
      "",
      idea ? `Story: ${idea}` : "A cinematic short made in S-Studio.",
      "",
      "If you stayed for the ending, drop a comment: what would YOU do next?",
    ].join("\n");

  async function copyValue(label: string, text: string) {
    const ok = await copyText(text);
    onStatus?.(ok ? `${label} copied — paste into YouTube Studio.` : "Copy failed — select the text manually.");
  }

  async function onRegenerate() {
    if (!jobId) return;
    setBusy(true);
    onStatus?.("Generating a fresh YouTube SEO pack…");
    try {
      const detail = await regenerateYoutubePack(jobId);
      if (detail.youtube_pack) onPackUpdated?.(detail.youtube_pack);
      onStatus?.(detail.message || "YouTube SEO pack ready.");
    } catch (err) {
      onStatus?.(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="yt-reach">
      <p className="panel-note">
        Unique SEO pack for this film ({pack?.mode || (aspectRatio === "9:16" ? "shorts" : "longform")}
        {pack?.source ? ` · ${pack.source}` : ""}). Checkmarks tick as each stage finishes ({completed}/
        {steps.length}).
      </p>

      <div className="yt-reach-actions" style={{ marginBottom: "0.75rem" }}>
        <button type="button" className="cta secondary" onClick={onRegenerate} disabled={!jobId || busy}>
          {busy ? "Generating pack…" : "Regenerate SEO pack"}
        </button>
      </div>

      <div className="yt-reach-pack">
        <div className="yt-reach-pack-card">
          <header>
            <strong>Primary title</strong>
            <button type="button" className="cta ghost" onClick={() => copyValue("Title", titleIdea)}>
              Copy
            </button>
          </header>
          <p>{titleIdea}</p>
        </div>

        {(pack?.alt_titles || []).length > 0 ? (
          <div className="yt-reach-pack-card">
            <header>
              <strong>Alt titles</strong>
              <button
                type="button"
                className="cta ghost"
                onClick={() => copyValue("Alt titles", (pack?.alt_titles || []).join("\n"))}
              >
                Copy
              </button>
            </header>
            <pre>{(pack?.alt_titles || []).join("\n")}</pre>
          </div>
        ) : null}

        <div className="yt-reach-pack-card">
          <header>
            <strong>Description</strong>
            <button
              type="button"
              className="cta ghost"
              onClick={() => copyValue("Description", descriptionIdea)}
            >
              Copy
            </button>
          </header>
          <pre>{descriptionIdea}</pre>
        </div>

        {(pack?.tags || []).length > 0 ? (
          <div className="yt-reach-pack-card">
            <header>
              <strong>Tags</strong>
              <button
                type="button"
                className="cta ghost"
                onClick={() => copyValue("Tags", (pack?.tags || []).join(", "))}
              >
                Copy
              </button>
            </header>
            <p>{(pack?.tags || []).join(", ")}</p>
          </div>
        ) : null}

        {(pack?.hashtags || []).length > 0 ? (
          <div className="yt-reach-pack-card">
            <header>
              <strong>Hashtags</strong>
              <button
                type="button"
                className="cta ghost"
                onClick={() => copyValue("Hashtags", (pack?.hashtags || []).join(" "))}
              >
                Copy
              </button>
            </header>
            <p>{(pack?.hashtags || []).join(" ")}</p>
          </div>
        ) : null}

        {pack?.pinned_comment ? (
          <div className="yt-reach-pack-card">
            <header>
              <strong>Pinned comment</strong>
              <button
                type="button"
                className="cta ghost"
                onClick={() => copyValue("Pinned comment", pack.pinned_comment || "")}
              >
                Copy
              </button>
            </header>
            <p>{pack.pinned_comment}</p>
          </div>
        ) : null}

        {(pack?.chapters || []).length > 0 ? (
          <div className="yt-reach-pack-card">
            <header>
              <strong>Chapters</strong>
              <button
                type="button"
                className="cta ghost"
                onClick={() => copyValue("Chapters", formatChapters(pack))}
              >
                Copy
              </button>
            </header>
            <pre>{formatChapters(pack)}</pre>
          </div>
        ) : null}
      </div>

      <ol className="yt-reach-steps">
        {steps.map((step) => {
          const checked = Boolean(autoDone[step.id]);
          return (
            <li key={step.id} className={checked ? "done" : "pending"}>
              <div className="yt-reach-step">
                <input type="checkbox" checked={checked} readOnly disabled />
                <span>
                  <strong>{step.title}</strong>
                  <span className="yt-reach-pipeline">
                    {checked ? "✓ Pipeline complete — " : "○ Waiting — "}
                    {step.pipeline}
                  </span>
                  <span className="yt-reach-body">{step.body}</span>
                  {step.tip ? <span className="yt-reach-tip">{step.tip}</span> : null}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
