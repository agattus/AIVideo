import { useMemo } from "react";
import { Link } from "react-router-dom";
import { VideoCard } from "../components/VideoCard";
import { useYtCatalog } from "../CatalogContext";

export function YtSubscriptionsPage() {
  const { videos } = useYtCatalog();

  const channels = useMemo(() => {
    const map = new Map<string, { name: string; avatar: string; handle: string; count: number }>();
    for (const v of videos) {
      const prev = map.get(v.channel) || {
        name: v.channel,
        avatar: v.channelAvatar,
        handle: v.channelHandle,
        count: 0,
      };
      prev.count += 1;
      map.set(v.channel, prev);
    }
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [videos]);

  const latest = useMemo(
    () => videos.filter((v) => !v.isShort).slice(0, 12),
    [videos],
  );

  return (
    <div className="yt-page">
      <header className="yt-page-head">
        <h1>Following</h1>
        <p className="yt-muted">Latest from creators you follow in S-Studio.</p>
      </header>

      <div className="yt-channel-strip" aria-label="Channels">
        {channels.map((c) => (
          <Link
            key={c.name}
            className="yt-channel-chip"
            to={`/results?q=${encodeURIComponent(c.name)}`}
          >
            <img src={c.avatar} alt="" />
            <span>{c.name}</span>
          </Link>
        ))}
      </div>

      <section className="yt-grid">
        {latest.map((video) => (
          <VideoCard key={video.id} video={video} />
        ))}
      </section>
    </div>
  );
}
