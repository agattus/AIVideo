import type { JobStatusResponse, WorkspaceResponse } from "../api/types";

/** Step ids for the YouTube reach checklist (pipeline-linked). */
export const YT_REACH_STEP_IDS = [
  "hook",
  "title",
  "thumb",
  "desc",
  "packaging",
  "end",
  "timing",
  "firsthour",
  "retention",
  "series",
] as const;

export type YtReachStepId = (typeof YT_REACH_STEP_IDS)[number];

/**
 * Map live job/workspace state → auto-checked YouTube reach steps.
 * Ticks advance as Generate → script → voice → images → assemble completes.
 */
export function deriveYoutubeReachAutoDone(
  status: JobStatusResponse | null,
  workspace: WorkspaceResponse | null,
): Record<YtReachStepId, boolean> {
  const st = status?.status || "";
  const pct = status?.progress_percent ?? 0;
  const title = (workspace?.title || status?.title || "").trim();
  const scenes = workspace?.scenes || [];
  const scriptReady =
    Boolean(workspace?.script_url) ||
    scenes.length > 0 ||
    st === "waiting_for_assets" ||
    st === "completed" ||
    pct >= 30;
  const audioReady =
    Boolean(workspace?.audio_ready || workspace?.audio_url) ||
    st === "waiting_for_assets" ||
    st === "completed" ||
    pct >= 60;
  const scenesReadyCount = workspace?.scenes_ready ?? 0;
  const allScenes =
    Boolean(workspace?.all_scenes_ready) ||
    (scenesReadyCount > 0 && scenesReadyCount === (workspace?.scene_count || 0));
  const hasThumb = scenesReadyCount >= 1 || Boolean(workspace?.video_url);
  const videoReady = Boolean(workspace?.video_url) || st === "completed";
  const assembling = st === "processing" && pct >= 80;
  const doneAssemble = videoReady || (assembling && pct >= 95);

  return {
    // Script engine cold-open + curiosity title
    hook: scriptReady,
    title: Boolean(title) || scriptReady,
    // First stills → thumbnail source
    thumb: hasThumb,
    // Script + voice locked → description pack
    desc: scriptReady && audioReady,
    // All (or enough) scene assets + prompts
    packaging: allScenes || Boolean(workspace?.prompts_url) || videoReady,
    // Final cut exists (ending locked for end-screen moment)
    end: doneAssemble || videoReady,
    // Upload kit ready once film is cut
    timing: videoReady,
    firsthour: videoReady,
    retention: videoReady,
    series: videoReady,
  };
}
