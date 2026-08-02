import type { ReactNode } from "react";

type Props = {
  id: string;
  title: string;
  summary?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  accent?: boolean;
};

export function StudioSection({
  id,
  title,
  summary,
  open,
  onToggle,
  children,
  accent = false,
}: Props) {
  return (
    <section id={id} className={`panel studio-section${accent ? " accent" : ""}`}>
      <button
        type="button"
        className="studio-section-toggle"
        aria-expanded={open}
        aria-controls={`${id}-body`}
        onClick={onToggle}
      >
        <span className="studio-section-title">
          <span className="studio-section-chevron" aria-hidden>
            {open ? "▾" : "▸"}
          </span>
          {title}
        </span>
        {summary ? <span className="studio-section-summary">{summary}</span> : null}
      </button>
      {open ? (
        <div id={`${id}-body`} className="studio-section-body">
          {children}
        </div>
      ) : null}
    </section>
  );
}
