import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CategoryChips } from "../components/CategoryChips";
import { VideoCard } from "../components/VideoCard";
import { useYtCatalog } from "../CatalogContext";
import { filterVideos } from "../hooks/useCatalog";

export function YtSearchPage() {
  const [params] = useSearchParams();
  const q = params.get("q") || "";
  const { videos } = useYtCatalog();
  const [category, setCategory] = useState("All");

  const results = useMemo(
    () => filterVideos(videos, { query: q, category }),
    [videos, q, category],
  );

  return (
    <div className="yt-page">
      <header className="yt-page-head">
        <h1>Results{q ? ` for “${q}”` : ""}</h1>
        <p className="yt-muted">{results.length} videos</p>
      </header>
      <CategoryChips active={category} onChange={setCategory} />
      <div className="yt-results">
        {results.map((video) => (
          <VideoCard key={video.id} video={video} horizontal />
        ))}
      </div>
      {results.length === 0 ? (
        <p className="yt-empty">No matches. Try another search.</p>
      ) : null}
    </div>
  );
}
