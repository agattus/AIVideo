import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useYtCatalog } from "../CatalogContext";
import { IconDislike, IconLike, IconShare } from "../components/Icons";

export function YtShortsPage() {
  const { videos } = useYtCatalog();
  const [params] = useSearchParams();
  const shorts = useMemo(() => videos.filter((v) => v.isShort), [videos]);
  const startId = params.get("v");
  const startIndex = Math.max(
    0,
    shorts.findIndex((v) => v.id === startId),
  );
  const [index, setIndex] = useState(startIndex === -1 ? 0 : startIndex);
  const touchY = useRef<number | null>(null);

  useEffect(() => {
    setIndex(startIndex === -1 ? 0 : startIndex);
  }, [startIndex]);

  const current = shorts[index];

  function step(delta: number) {
    if (!shorts.length) return;
    setIndex((i) => (i + delta + shorts.length) % shorts.length);
  }

  if (!current) {
    return (
      <div className="yt-shorts-empty">
        <h1>No Clips yet</h1>
        <p className="yt-muted">Upload a vertical video — or make one in Studio.</p>
      </div>
    );
  }

  return (
    <div
      className="yt-shorts"
      onWheel={(e) => {
        if (Math.abs(e.deltaY) < 40) return;
        step(e.deltaY > 0 ? 1 : -1);
      }}
      onTouchStart={(e) => {
        touchY.current = e.touches[0]?.clientY ?? null;
      }}
      onTouchEnd={(e) => {
        if (touchY.current == null) return;
        const dy = (e.changedTouches[0]?.clientY ?? touchY.current) - touchY.current;
        if (Math.abs(dy) > 50) step(dy < 0 ? 1 : -1);
        touchY.current = null;
      }}
    >
      <div className="yt-short-stage">
        <video
          key={current.id}
          className="yt-short-video"
          src={current.videoUrl || undefined}
          poster={current.thumbnail}
          autoPlay
          muted
          loop
          playsInline
          controls={false}
        />
        <div className="yt-short-overlay">
          <div className="yt-short-meta">
            <p className="yt-short-channel">@{current.channelHandle.replace(/^@/, "")}</p>
            <h1>{current.title}</h1>
            <p className="yt-muted">{current.views}</p>
          </div>
          <div className="yt-short-actions">
            <button type="button">
              <IconLike />
              <span>{current.likes}</span>
            </button>
            <button type="button">
              <IconDislike />
              <span>Dislike</span>
            </button>
            <button type="button">
              <IconShare />
              <span>Share</span>
            </button>
          </div>
        </div>
        <div className="yt-short-nav">
          <button type="button" onClick={() => step(-1)} aria-label="Previous clip">
            ▲
          </button>
          <button type="button" onClick={() => step(1)} aria-label="Next clip">
            ▼
          </button>
        </div>
      </div>
    </div>
  );
}
