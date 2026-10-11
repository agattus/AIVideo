import { useCallback, useEffect, useMemo, useState } from "react";
import { listJobs } from "../../api/client";
import type { JobSummary } from "../../api/types";
import { DEMO_VIDEOS } from "../data/mockVideos";
import type { YtVideo } from "../types";

const UPLOAD_KEY = "sstudio-local-uploads-v1";

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
    channel: "You",
    channelHandle: "@you",
    channelAvatar: "https://picsum.photos/seed/sstudio/88/88",
    views: job.status === "completed" ? "Your library" : job.status.replace(/_/g, " "),
    uploadedAt: relativeFromIso(job.updated_at),
    duration: job.scene_count ? `${job.scene_count} scenes` : "—",
    thumbnail:
      job.thumb_url ||
      job.video_url ||
      `https://picsum.photos/seed/${encodeURIComponent(job.job_id)}/640/360`,
    videoUrl: job.video_url,
    description: shortIdea || "Made in S-Studio.",
    category: "Your films",
    likes: "—",
    subscribers: "You",
    source: "library",
    canEdit: Boolean(job.can_edit),
    heat: "Rising",
  };
}

function readUploads(): YtVideo[] {
  try {
    const raw = sessionStorage.getItem(UPLOAD_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as YtVideo[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeUploads(list: YtVideo[]) {
  try {
    // Object URLs don't survive reload; keep metadata only for session display.
    const serializable = list.map((v) => ({
      ...v,
      videoUrl: v.videoUrl?.startsWith("blob:") ? null : v.videoUrl,
      thumbnail: v.thumbnail.startsWith("blob:")
        ? "https://picsum.photos/seed/upload-fallback/640/360"
        : v.thumbnail,
    }));
    sessionStorage.setItem(UPLOAD_KEY, JSON.stringify(serializable));
  } catch {
    /* ignore quota */
  }
}

function withHeat(videos: YtVideo[]): YtVideo[] {
  return videos.map((v, i) => {
    if (v.heat) return v;
    if (v.source === "upload") return { ...v, heat: "Just dropped" };
    if (v.isLive) return { ...v, heat: "Live now" };
    if (i < 3) return { ...v, heat: "Going viral" };
    if (i < 7) return { ...v, heat: "Trending" };
    return { ...v, heat: "Rising" };
  });
}

export function useCatalog() {
  const [library, setLibrary] = useState<YtVideo[]>([]);
  const [uploads, setUploads] = useState<YtVideo[]>(() => readUploads());
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

  const addUpload = useCallback((video: YtVideo) => {
    setUploads((prev) => {
      const next = [video, ...prev].slice(0, 24);
      writeUploads(next);
      return next;
    });
  }, []);

  const videos = useMemo(() => {
    const demoIds = new Set(DEMO_VIDEOS.map((v) => v.id));
    const uniqueLib = library.filter((v) => !demoIds.has(v.id));
    return withHeat([...uploads, ...uniqueLib, ...DEMO_VIDEOS]);
  }, [library, uploads]);

  const byId = useMemo(() => {
    const map = new Map<string, YtVideo>();
    for (const v of videos) map.set(v.id, v);
    return map;
  }, [videos]);

  return {
    videos,
    byId,
    library,
    uploads,
    loading,
    error,
    refresh,
    addUpload,
  };
}

export function filterVideos(
  videos: YtVideo[],
  opts: { query?: string; category?: string; shortsOnly?: boolean },
): YtVideo[] {
  let list = videos;
  if (opts.shortsOnly) list = list.filter((v) => v.isShort);
  if (opts.category && opts.category !== "All") {
    if (opts.category === "Recently uploaded" || opts.category === "Fresh") {
      list = [...list].slice(0, 10);
    } else if (opts.category === "Going viral" || opts.category === "Trending") {
      list = list.filter((v) => v.heat === "Going viral" || v.heat === "Trending");
    } else if (opts.category === "Your films") {
      list = list.filter((v) => v.source === "library" || v.source === "upload");
    } else {
      list = list.filter(
        (v) =>
          v.category === opts.category ||
          (opts.category === "Clips" && v.isShort) ||
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
