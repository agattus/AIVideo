import { useCallback, useEffect, useMemo, useState } from "react";
import { listJobs } from "../../api/client";
import type { JobSummary } from "../../api/types";
import { DEMO_VIDEOS } from "../data/mockVideos";
import type { YtVideo } from "../types";

function relativeFromIso(iso?: string | null): string {
  if (!iso) return "Recently";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "Recently";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 60) return `${mins || 1} minutes ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hours ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} days ago`;
  return `${Math.round(days / 30)} months ago`;
}

function jobToVideo(job: JobSummary): YtVideo {
  const title = (job.title || job.idea || "Untitled film").trim();
  const shortIdea = (job.idea || "").trim();
  return {
    id: `lib-${job.job_id}`,
    jobId: job.job_id,
    title,
    channel: "S-Studio",
    channelHandle: "@sstudio",
    channelAvatar: "https://picsum.photos/seed/sstudio/88/88",
    views: job.status === "completed" ? "Your library" : job.status.replace(/_/g, " "),
    uploadedAt: relativeFromIso(job.updated_at),
    duration: job.scene_count ? `${job.scene_count} scenes` : "—",
    thumbnail:
      job.thumb_url ||
      job.video_url ||
      `https://picsum.photos/seed/${encodeURIComponent(job.job_id)}/640/360`,
    videoUrl: job.video_url,
    description: shortIdea || "Generated in S-Studio.",
    category: "Your films",
    likes: "—",
    subscribers: "You",
    source: "library",
    canEdit: Boolean(job.can_edit),
  };
}

export function useCatalog() {
  const [library, setLibrary] = useState<YtVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const jobs = await listJobs(40);
      setLibrary(jobs.map(jobToVideo));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load library.");
      setLibrary([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const videos = useMemo(() => {
    // Library films first so creators see their work, then demos fill the feed.
    const demoIds = new Set(DEMO_VIDEOS.map((v) => v.id));
    const uniqueLib = library.filter((v) => !demoIds.has(v.id));
    return [...uniqueLib, ...DEMO_VIDEOS];
  }, [library]);

  const byId = useMemo(() => {
    const map = new Map<string, YtVideo>();
    for (const v of videos) map.set(v.id, v);
    return map;
  }, [videos]);

  return { videos, byId, library, loading, error, refresh };
}

export function filterVideos(
  videos: YtVideo[],
  opts: { query?: string; category?: string; shortsOnly?: boolean },
): YtVideo[] {
  let list = videos;
  if (opts.shortsOnly) list = list.filter((v) => v.isShort);
  if (opts.category && opts.category !== "All") {
    if (opts.category === "Recently uploaded") {
      list = [...list].slice(0, 8);
    } else if (opts.category === "Watched") {
      list = list.filter((v) => v.source === "library");
    } else if (opts.category === "Your films") {
      list = list.filter((v) => v.source === "library");
    } else {
      list = list.filter(
        (v) =>
          v.category === opts.category ||
          (opts.category === "Shorts" && v.isShort) ||
          (opts.category === "Live" && v.isLive),
      );
    }
  }
  const q = (opts.query || "").trim().toLowerCase();
  if (q) {
    list = list.filter(
      (v) =>
        v.title.toLowerCase().includes(q) ||
        v.channel.toLowerCase().includes(q) ||
        v.description.toLowerCase().includes(q) ||
        v.category.toLowerCase().includes(q),
    );
  }
  return list;
}
