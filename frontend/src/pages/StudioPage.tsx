import { Link, useParams } from "react-router-dom";
import { JobStudio } from "../components/JobStudio";

export function StudioPage() {
  const { jobId } = useParams<{ jobId?: string }>();

  if (!jobId) {
    return (
      <section className="hero">
        <p className="brand-mark">Studio</p>
        <h1 className="headline">Open a film to edit.</h1>
        <p className="lede">
          Generate a new idea on Compose, or reopen a previous film from the library.
        </p>
        <div className="inline-actions" style={{ marginTop: "1.25rem" }}>
          <Link className="cta" to="/">
            Compose a film
          </Link>
          <Link className="cta secondary" to="/#library">
            Browse library
          </Link>
        </div>
      </section>
    );
  }

  return <JobStudio jobId={jobId} />;
}
