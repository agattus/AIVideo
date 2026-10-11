import { Link } from "react-router-dom";
import type { YtVideo } from "../types";
import { IconVerified } from "./Icons";

type Props = {
  video: YtVideo;
  dense?: boolean;
  horizontal?: boolean;
};

export function VideoCard({ video, dense, horizontal }: Props) {
  const to = video.isShort
    ? `/clips?v=${encodeURIComponent(video.id)}`
    : `/watch/${video.id}`;

  if (horizontal) {
    return (
      <Link className="yt-related-card" to={to}>
        <div className="yt-related-thumb">
          <img src={video.thumbnail} alt="" loading="lazy" />
          <span className="yt-duration">{video.duration}</span>
        </div>
        <div className="yt-related-meta">
          <h3 className="yt-related-title">{video.title}</h3>
          <p className="yt-muted">
            {video.channel}
            {video.verified ? (
              <span className="yt-verified" title="Verified">
                <IconVerified size={12} />
              </span>
            ) : null}
          </p>
          <p className="yt-muted">
            {video.views} · {video.uploadedAt}
          </p>
          {video.heat ? <p className="ss-heat">{video.heat}</p> : null}
        </div>
      </Link>
    );
  }

  return (
    <Link className={`yt-card${dense ? " dense" : ""}`} to={to}>
      <div className="yt-thumb-wrap">
        <img className="yt-thumb" src={video.thumbnail} alt="" loading="lazy" />
        {video.isLive ? <span className="yt-live-badge">LIVE</span> : null}
        <span className="yt-duration">{video.duration}</span>
      </div>
      <div className="yt-card-body">
        <img className="yt-avatar" src={video.channelAvatar} alt="" loading="lazy" />
        <div className="yt-card-text">
          <h3 className="yt-card-title">{video.title}</h3>
          <p className="yt-muted">
            {video.channel}
            {video.verified ? (
              <span className="yt-verified" title="Verified">
                <IconVerified size={12} />
              </span>
            ) : null}
          </p>
          <p className="yt-muted">
            {video.views} · {video.uploadedAt}
          </p>
          {video.heat ? <p className="ss-heat">{video.heat}</p> : null}
        </div>
      </div>
    </Link>
  );
}
