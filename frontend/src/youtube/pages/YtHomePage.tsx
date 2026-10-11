import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { VideoCard } from "../components/VideoCard";
import { useYtCatalog } from "../CatalogContext";
import { filterVideos } from "../hooks/useCatalog";

const FILTERS = ["All", "Going viral", "Fresh", "Clips", "Your films"] as const;

export function YtHomePage() {
  const { videos, loading, error } = useYtCatalog();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");

  const filtered = useMemo(
    () => filterVideos(videos, { category: filter }),
    [videos, filter],
  );

  const clips = useMemo(
    () => videos.filter((v) => v.isShort).slice(0, 10),
    [videos],
  );

  const heroVisual =
    videos.find((v) => !v.isShort)?.thumbnail ||
    "https://picsum.photos/seed/sstudio-hero/1200/900";

  return (
    <div className="yt-home">
      <section className="ss-hero" aria-label="S-Studio">
        <div className="ss-hero-copy">
          <p className="ss-brand">
            S-<span>Studio</span>
          </p>
          <h1>Upload anything. Get seen.</h1>
          <p className="ss-hero-lede">
            Drop a clip or a full film. The feed boosts what people can’t stop
            watching — so anyone can go viral.
          </p>
          <div className="ss-hero-ctas">
            <Link className="ss-btn primary" to="/upload">
              Upload a video
            </Link>
            <Link className="ss-btn secondary" to="/create">
              Make one with AI
            </Link>
          </div>
        </div>
        <div className="ss-hero-visual">
          <img src={heroVisual} alt="" />
        </div>
      </section>

      {error ? (
        <p className="yt-banner">
          Showing the public discovery feed. Your library will appear when Studio is online.
        </p>
      ) : null}
      {loading ? <p className="yt-banner">Loading the feed…</p> : null}

      <section className="ss-section" aria-label="Trending">
        <div className="ss-section-head">
          <div>
            <h2>What’s catching fire</h2>
            <p>Fresh uploads and films climbing the feed right now.</p>
          </div>
          <Link className="ss-link" to="/upload">
            Post yours
          </Link>
        </div>

        <div className="ss-filters" role="tablist" aria-label="Feed filters">
          {FILTERS.map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={filter === item}
              className={`ss-filter${filter === item ? " active" : ""}`}
              onClick={() => setFilter(item)}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="ss-grid">
          {filtered
            .filter((v) => (filter === "All" ? !v.isShort : true))
            .map((video, i) => (
              <div
                key={video.id}
                style={{ animationDelay: `${Math.min(i, 10) * 45}ms` }}
              >
                <VideoCard video={video} />
              </div>
            ))}
        </div>

        {!loading && filtered.length === 0 ? (
          <p className="yt-empty">Nothing here yet — be the first to upload.</p>
        ) : null}
      </section>

      {clips.length > 0 ? (
        <section className="ss-section yt-shorts-rail" aria-label="Clips">
          <div className="ss-section-head">
            <div>
              <h2>Clips in motion</h2>
              <p>Vertical hits made for quick shares.</p>
            </div>
            <Link className="ss-link" to="/clips">
              Open Clips
            </Link>
          </div>
          <div className="yt-shorts-row">
            {clips.map((video) => (
              <VideoCard key={video.id} video={video} dense />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
