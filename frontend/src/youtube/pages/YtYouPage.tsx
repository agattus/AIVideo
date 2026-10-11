import { Link } from "react-router-dom";
import { VideoCard } from "../components/VideoCard";
import { useYtCatalog } from "../CatalogContext";

export function YtYouPage() {
  const { library, videos, refresh, loading } = useYtCatalog();
  const history = videos.filter((v) => !v.isShort).slice(0, 8);
  const liked = videos.filter((v) => v.verified).slice(0, 6);

  return (
    <div className="yt-page yt-you">
      <header className="yt-you-head">
        <div className="yt-avatar-btn xl">S</div>
        <div>
          <h1>Your stage</h1>
          <p className="yt-muted">@you · {library.length} films ready to push</p>
          <div className="yt-you-links">
            <Link to="/upload">Upload</Link>
            <Link to="/create">Create with AI</Link>
            <Link to="/studio">Studio</Link>
            <button type="button" onClick={() => refresh()} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>
      </header>

      <section id="history" className="yt-you-section">
        <div className="yt-section-head">
          <h2>History</h2>
        </div>
        <div className="yt-h-scroll">
          {history.map((v) => (
            <div className="yt-h-item" key={v.id}>
              <VideoCard video={v} dense />
            </div>
          ))}
        </div>
      </section>

      <section id="playlists" className="yt-you-section">
        <div className="yt-section-head">
          <h2>Playlists</h2>
        </div>
        <div className="yt-playlist-row">
          <Link className="yt-playlist-card" to="/">
            <div className="yt-playlist-art">Home mix</div>
            <p>Watch later · {history.length} videos</p>
          </Link>
          <Link className="yt-playlist-card" to="/clips">
            <div className="yt-playlist-art alt">Clips mix</div>
            <p>Liked Clips</p>
          </Link>
          <Link className="yt-playlist-card" to="/create">
            <div className="yt-playlist-art studio">Studio drafts</div>
            <p>Open compose</p>
          </Link>
        </div>
      </section>

      <section id="watch-later" className="yt-you-section">
        <div className="yt-section-head">
          <h2>Your films</h2>
        </div>
        {library.length === 0 ? (
          <p className="yt-empty">
            No pipeline jobs yet.{" "}
            <Link to="/create">Create a film</Link> to see it here.
          </p>
        ) : (
          <div className="yt-grid">
            {library.map((v) => (
              <VideoCard key={v.id} video={v} />
            ))}
          </div>
        )}
      </section>

      <section id="liked" className="yt-you-section">
        <div className="yt-section-head">
          <h2>Liked videos</h2>
        </div>
        <div className="yt-grid">
          {liked.map((v) => (
            <VideoCard key={v.id} video={v} />
          ))}
        </div>
      </section>
    </div>
  );
}
