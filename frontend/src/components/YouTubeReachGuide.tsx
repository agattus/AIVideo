import { useMemo } from "react";
import { copyText } from "../api/client";
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
  filmTitle: string;
  idea?: string;
  style?: string;
  aspectRatio?: string;
  autoDone: Record<YtReachStepId, boolean>;
  onStatus?: (message: string) => void;
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
      pipeline: "Ticks when the film title exists",
      body: `Title is generated for YouTube curiosity (under ~70 chars). Pattern: concrete noun + tension — e.g. “${short}”.`,
      tip: "Auto from script title field.",
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
      pipeline: "Ticks when script + voiceover are ready",
      body: "Copy the description draft below into YouTube. First 2 lines = hook + keyword; then synopsis + comment CTA.",
      tip: "Auto after Phase 1 (script + TTS).",
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

export function YouTubeReachGuide({
  filmTitle,
  idea = "",
  style = "",
  aspectRatio = "16:9",
  autoDone,
  onStatus,
}: Props) {
  const steps = useMemo(
    () => buildSteps(filmTitle || "Untitled film", idea, style, aspectRatio),
    [filmTitle, idea, style, aspectRatio],
  );

  const completed = YT_REACH_STEP_IDS.filter((id) => autoDone[id]).length;

  const titleIdea = useMemo(() => {
    const base = filmTitle || "Untitled film";
    if (base.length <= 65) return `${base} (you won’t believe the ending)`;
    return base.slice(0, 70);
  }, [filmTitle]);

  const descriptionIdea = useMemo(() => {
    const t = filmTitle || "this film";
    return [
      `${t} — watch till the end.`,
      "",
      idea ? `Story: ${idea}` : "A cinematic short made in S-Studio.",
      "",
      "In this video:",
      "• The setup",
      "• The twist",
      "• What it means",
      "",
      "If you stayed for the ending, drop a comment: what would YOU do next?",
      "",
      "#shorts #story #cinematic #mystery",
    ].join("\n");
  }, [filmTitle, idea]);

  async function copyPack(kind: "title" | "description") {
    const text = kind === "title" ? titleIdea : descriptionIdea;
    const ok = await copyText(text);
    onStatus?.(
      ok
        ? kind === "title"
          ? "Title draft copied — paste into YouTube Studio."
          : "Description draft copied — paste into YouTube Studio."
        : "Copy failed — select the text manually.",
    );
  }

  return (
    <div className="yt-reach">
      <p className="panel-note">
        These steps track your Generate → Assemble pipeline automatically.
        Checkmarks tick as each stage finishes ({completed}/{steps.length}).
      </p>

      <div className="yt-reach-pack">
        <div className="yt-reach-pack-card">
          <header>
            <strong>Title draft</strong>
            <button type="button" className="cta ghost" onClick={() => copyPack("title")}>
              Copy
            </button>
          </header>
          <p>{titleIdea}</p>
        </div>
        <div className="yt-reach-pack-card">
          <header>
            <strong>Description draft</strong>
            <button type="button" className="cta ghost" onClick={() => copyPack("description")}>
              Copy
            </button>
          </header>
          <pre>{descriptionIdea}</pre>
        </div>
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
