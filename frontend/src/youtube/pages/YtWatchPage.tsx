import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DEMO_COMMENTS } from "../data/mockVideos";
import { useYtCatalog } from "../CatalogContext";
import { VideoCard } from "../components/VideoCard";
import {
  IconDislike,
  IconLike,
  IconMore,
  IconShare,
  IconVerified,
} from "../components/Icons";

export function YtWatchPage() {
  const { videoId = "" } = useParams();
  const { byId, videos } = useYtCatalog();
  const navigate = useNavigate();
  const video = byId.get(videoId);
  const [liked, setLiked] = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [descOpen, setDescOpen] = useState(false);

  const related = useMemo(
    () => videos.filter((v) => v.id !== videoId && !v.isShort).slice(0, 12),
    [videos, videoId],
  );

  if (!video) {
    return (
      <div className="yt-watch missing">
        <h1>Video unavailable</h1>
        <p className="yt-muted">This video isn’t in the catalog.</p>
        <Link className="yt-text-btn" to="/">
          Back to Home
        </Link>
      </div>
    );
  }

  return (
    <div className="yt-watch">
      <div className="yt-watch-primary">
        <div className="yt-player">
          {video.videoUrl ? (
            <video
              key={video.id}
              src={video.videoUrl}
              poster={video.thumbnail}
              controls
              autoPlay
              playsInline
            />
          ) : (
            <div className="yt-player-empty">
              <img src={video.thumbnail} alt="" />
              <p>No stream yet — open in Studio to assemble.</p>
              {video.jobId ? (
                <button
                  type="button"
                  className="yt-subscribe"
                  onClick={() => navigate(`/studio/${video.jobId}`)}
                >
                  Open Studio
                </button>
              ) : null}
            </div>
          )}
        </div>

        <h1 className="yt-watch-title">{video.title}</h1>

        <div className="yt-watch-toolbar">
          <div className="yt-channel-row">
            <img className="yt-avatar lg" src={video.channelAvatar} alt="" />
            <div>
              <p className="yt-channel-name">
                {video.channel}
                {video.verified ? (
                  <span className="yt-verified">
                    <IconVerified size={14} />
                  </span>
                ) : null}
              </p>
              <p className="yt-muted sm">{video.subscribers} subscribers</p>
            </div>
            <button
              type="button"
              className={`yt-subscribe${subscribed ? " on" : ""}`}
              onClick={() => setSubscribed((v) => !v)}
            >
              {subscribed ? "Subscribed" : "Subscribe"}
            </button>
          </div>

          <div className="yt-actions">
            <div className="yt-action-pill">
              <button
                type="button"
                className={liked ? "on" : undefined}
                onClick={() => setLiked((v) => !v)}
                aria-pressed={liked}
              >
                <IconLike size={20} /> {liked ? "Liked" : video.likes}
              </button>
              <span className="yt-action-sep" />
              <button type="button" aria-label="Dislike">
                <IconDislike size={20} />
              </button>
            </div>
            <button type="button" className="yt-action-pill">
              <IconShare size={20} /> Share
            </button>
            <button type="button" className="yt-action-pill" aria-label="More">
              <IconMore size={20} />
            </button>
            {video.jobId ? (
              <button
                type="button"
                className="yt-action-pill"
                onClick={() => navigate(`/studio/${video.jobId}`)}
              >
                Studio
              </button>
            ) : null}
          </div>
        </div>

        <button
          type="button"
          className={`yt-desc${descOpen ? " open" : ""}`}
          onClick={() => setDescOpen((v) => !v)}
        >
          <p className="yt-desc-meta">
            {video.views} · {video.uploadedAt}
          </p>
          <p className="yt-desc-body">{video.description}</p>
          <span className="yt-desc-more">{descOpen ? "Show less" : "…more"}</span>
        </button>

        <section className="yt-comments">
          <h2>{DEMO_COMMENTS.length} Comments</h2>
          <div className="yt-comment-compose">
            <div className="yt-avatar-btn sm">S</div>
            <input type="text" placeholder="Add a comment…" aria-label="Add a comment" />
          </div>
          {DEMO_COMMENTS.map((c) => (
            <article className="yt-comment" key={c.id}>
              <img className="yt-avatar" src={c.avatar} alt="" />
              <div>
                <p className="yt-comment-head">
                  <strong>{c.author}</strong>
                  <span className="yt-muted sm">{c.postedAt}</span>
                </p>
                <p>{c.text}</p>
                <p className="yt-comment-likes">
                  <IconLike size={16} /> {c.likes}
                </p>
              </div>
            </article>
          ))}
        </section>
      </div>

      <aside className="yt-watch-related" aria-label="Related videos">
        {related.map((v) => (
          <VideoCard key={v.id} video={v} horizontal />
        ))}
      </aside>
    </div>
  );
}
