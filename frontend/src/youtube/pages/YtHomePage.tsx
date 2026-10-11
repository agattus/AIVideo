import { useMemo, useState } from "react";
import { CategoryChips } from "../components/CategoryChips";
import { VideoCard } from "../components/VideoCard";
import { useYtCatalog } from "../CatalogContext";
import { filterVideos } from "../hooks/useCatalog";

export function YtHomePage() {
  const { videos, loading, error, library } = useYtCatalog();
  const [category, setCategory] = useState("All");

  const filtered = useMemo(
    () => filterVideos(videos, { category }),
    [videos, category],
  );

  const shorts = useMemo(
    () => videos.filter((v) => v.isShort).slice(0, 8),
    [videos],
  );

  return (
    <div className="yt-home">
      <CategoryChips
        active={category}
        onChange={setCategory}
        extra={library.length ? ["Your films"] : []}
      />

      {error ? (
        <p className="yt-banner warn">
          Library offline — showing demo feed. {error}
        </p>
      ) : null}

      {loading ? <p className="yt-banner">Loading your films…</p> : null}

      {category === "All" && shorts.length > 0 ? (
        <section className="yt-shorts-rail" aria-label="Clips">
          <div className="yt-shorts-head">
            <h2>Clips</h2>
          </div>
          <div className="yt-shorts-row">
            {shorts.map((video) => (
              <VideoCard key={video.id} video={video} dense />
            ))}
          </div>
        </section>
      ) : null}

      <section className="yt-grid" aria-label="Recommended">
        {filtered
          .filter((v) => (category === "All" ? !v.isShort : true))
          .map((video, i) => (
            <div
              key={video.id}
              className="yt-grid-item"
              style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
            >
              <VideoCard video={video} />
            </div>
          ))}
      </section>

      {!loading && filtered.length === 0 ? (
        <p className="yt-empty">No videos in this category yet.</p>
      ) : null}
    </div>
  );
}
