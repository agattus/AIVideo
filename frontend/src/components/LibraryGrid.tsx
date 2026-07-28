import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listJobs, reopenJob } from "../api/client";
import type { JobSummary } from "../api/types";
import { StatusPill } from "./ProgressMeter";

export function LibraryGrid() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJobs(40);
      setJobs(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load previous jobs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function openJob(jobId: string, edit: boolean) {
    try {
      if (edit) {
        await reopenJob(jobId);
      }
      navigate(`/studio/${jobId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className="section" id="library">
      <div className="section-head">
        <div>
          <h2>Previous films</h2>
          <p>Reopen any past job to edit voiceover, BGM, images, or reassemble.</p>
        </div>
        <button type="button" className="cta secondary" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error ? <p className="error-banner">{error}</p> : null}

      {!loading && jobs.length === 0 ? (
        <p className="empty-note">
          No previous films found under the output directory yet — generate one above.
        </p>
      ) : null}

      <div className="library-grid">
        {jobs.map((job) => (
          <article className="library-item" key={job.job_id}>
            {job.thumb_url || job.video_url ? (
              <img
                className="library-thumb"
                src={job.thumb_url || job.video_url || ""}
                alt=""
              />
            ) : (
              <div className="library-thumb placeholder">No preview</div>
            )}
            <div className="library-body">
              <h3>{job.title || job.job_id}</h3>
              <p className="library-meta">
                <StatusPill status={job.status} /> · {job.scene_count || "?"} scenes
                {job.updated_at
                  ? ` · ${new Date(job.updated_at).toLocaleString()}`
                  : ""}
              </p>
              <p className="library-meta">{(job.idea || "").slice(0, 120)}</p>
              <div className="library-actions">
                <button
                  type="button"
                  className="cta secondary"
                  onClick={() => openJob(job.job_id, false)}
                >
                  Open
                </button>
                {job.can_edit ? (
                  <button
                    type="button"
                    className="cta"
                    onClick={() => openJob(job.job_id, true)}
                  >
                    Edit
                  </button>
                ) : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
