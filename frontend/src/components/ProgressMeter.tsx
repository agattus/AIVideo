import { useEffect, useState } from "react";
import type { JobStatus } from "../api/types";
import {
  friendlyStage,
  friendlyStatus,
  pickTip,
  tipsForStatus,
} from "../lib/progressCopy";

export function StatusPill({ status }: { status: JobStatus | string }) {
  return <span className={`status-pill ${status}`}>{friendlyStatus(status)}</span>;
}

export function ProgressMeter({
  percent,
  status,
  stage,
  scenesDone,
  scenesTotal,
}: {
  percent: number;
  status: string;
  stage?: string | null;
  scenesDone?: number | null;
  scenesTotal?: number | null;
}) {
  const pct = Math.max(0, Math.min(100, percent || 0));
  const waiting = status === "queued" || status === "processing";
  const tips = tipsForStatus(status, pct);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!tips.length) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 4200);
    return () => window.clearInterval(id);
  }, [tips.length, status]);

  const tip = pickTip(tips, tick);
  const total = scenesTotal && scenesTotal > 0 ? scenesTotal : null;
  const done =
    total != null && scenesDone != null ? Math.max(0, Math.min(scenesDone, total)) : null;
  const sceneLabel =
    done != null && total != null ? `Scene ${done} of ${total}` : null;
  const headline =
    sceneLabel && status === "processing" && pct >= 80
      ? `Rendering ${sceneLabel.toLowerCase()}…`
      : friendlyStage(stage);
  const scenePct =
    done != null && total != null ? Math.round((done / total) * 100) : null;

  return (
    <div className="progress-block">
      <div
        className="meter"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={headline}
      >
        <div className={`meter-fill${waiting ? " active" : ""}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="meter-meta">
        <span>
          {pct}%
          {sceneLabel ? ` · ${sceneLabel}` : ""}
        </span>
        <StatusPill status={status} />
      </div>
      <p className={`stage${waiting ? " stage-pulse" : ""}`}>{headline}</p>
      {scenePct != null && status === "processing" ? (
        <p className="loading-tip">
          {done} of {total} scene clips ready ({scenePct}%)
        </p>
      ) : tip ? (
        <p className="loading-tip" key={`${status}-${tick}`}>
          {tip}
        </p>
      ) : null}
    </div>
  );
}
