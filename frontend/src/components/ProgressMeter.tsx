import type { JobStatus } from "../api/types";

export function StatusPill({ status }: { status: JobStatus | string }) {
  return <span className={`status-pill ${status}`}>{status}</span>;
}

export function ProgressMeter({
  percent,
  status,
  stage,
}: {
  percent: number;
  status: string;
  stage?: string | null;
}) {
  const pct = Math.max(0, Math.min(100, percent || 0));
  return (
    <div className="progress-block">
      <div
        className="meter"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className="meter-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="meter-meta">
        <span>{pct}%</span>
        <StatusPill status={status} />
      </div>
      {stage ? <p className="stage">{stage}</p> : null}
    </div>
  );
}
