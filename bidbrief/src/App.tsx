import { useEffect, useState } from "react";
import {
  SAMPLE_TENDER,
  formatInr,
  type TenderBrief,
} from "./data/sampleTender";

type Stage = "landing" | "upload" | "processing" | "brief";
type BriefTab = "overview" | "eligibility" | "boq" | "documents" | "actions";

const STEPS: { id: Stage; label: string }[] = [
  { id: "landing", label: "Start" },
  { id: "upload", label: "Upload NIT" },
  { id: "processing", label: "Extract" },
  { id: "brief", label: "Bid brief" },
];

const PROCESS_MESSAGES = [
  "Reading NIT cover & tender number…",
  "Extracting EMD, LD, payment & PVC clauses…",
  "Parsing BOQ line items & units…",
  "Checking eligibility against contractor profile…",
  "Flagging risks & building document checklist…",
];

export default function App() {
  const [stage, setStage] = useState<Stage>("landing");
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState(0);
  const [processMsg, setProcessMsg] = useState(PROCESS_MESSAGES[0]);
  const [brief, setBrief] = useState<TenderBrief | null>(null);
  const [tab, setTab] = useState<BriefTab>("overview");

  useEffect(() => {
    if (stage !== "processing") return;

    setProgress(0);
    setProcessMsg(PROCESS_MESSAGES[0]);
    const started = Date.now();
    const duration = 2800;

    const tick = window.setInterval(() => {
      const pct = Math.min(100, ((Date.now() - started) / duration) * 100);
      setProgress(pct);
      const idx = Math.min(
        PROCESS_MESSAGES.length - 1,
        Math.floor((pct / 100) * PROCESS_MESSAGES.length),
      );
      setProcessMsg(PROCESS_MESSAGES[idx]);
      if (pct >= 100) {
        window.clearInterval(tick);
        setBrief(SAMPLE_TENDER);
        setTab("overview");
        setStage("brief");
      }
    }, 80);

    return () => window.clearInterval(tick);
  }, [stage]);

  const stepIndex = STEPS.findIndex((s) => s.id === stage);

  function startSample() {
    setStage("processing");
  }

  function onFileChosen() {
    setStage("processing");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-name">BidBrief</div>
          <div className="brand-tag">
            Railway electrical tenders → bid-ready brief
          </div>
        </div>
        <nav className="stepper" aria-label="Progress">
          {STEPS.map((s, i) => (
            <span
              key={s.id}
              className={`step${i === stepIndex ? " active" : ""}${i < stepIndex ? " done" : ""}`}
            >
              {s.label}
            </span>
          ))}
        </nav>
      </header>

      {stage === "landing" && (
        <section className="hero">
          <div className="hero-copy">
            <h1>Know if you should bid before you price the BOQ.</h1>
            <p>
              Upload an Indian Railways electrical NIT PDF. BidBrief extracts
              commercial terms, eligibility, risks, BOQ lines, and the document
              pack a contractor must finish before submission.
            </p>
            <div className="cta-row">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setStage("upload")}
              >
                Upload tender PDF
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={startSample}
              >
                Try sample WR/TRD tender
              </button>
            </div>
          </div>
          <aside className="hero-visual" aria-hidden="true">
            <div className="hero-kicker">Sample preview</div>
            <h2>Valsad TSS — 25kV OHE switching</h2>
            <div className="hero-meta">
              <div>
                <span>Authority</span>
                Western Railway · TRD
              </div>
              <div>
                <span>Estimate</span>
                ₹4.85 Cr
              </div>
              <div>
                <span>EMD</span>
                ₹9.7 Lakh
              </div>
              <div>
                <span>Deadline</span>
                28 Apr 2026
              </div>
            </div>
          </aside>
        </section>
      )}

      {stage === "upload" && (
        <section className="panel">
          <h2>Upload NIT / tender PDF</h2>
          <p className="panel-lead">
            Works best with IREPS-style NITs: cover page, eligibility,
            commercial conditions, and schedule of quantities.
          </p>
          <div
            className={`upload-zone${drag ? " drag" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              onFileChosen();
            }}
          >
            <strong>Drop tender PDF here</strong>
            <p>or choose a file — prototype uses a sample railway electrical NIT</p>
            <div className="cta-row" style={{ justifyContent: "center" }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={onFileChosen}
              >
                Choose PDF
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={startSample}
              >
                Use sample instead
              </button>
            </div>
          </div>
          <p className="footer-note">
            v0 parses a fixed sample so you can demo the contractor workflow
            without an API key. Next: real PDF + OCR extraction.
          </p>
        </section>
      )}

      {stage === "processing" && (
        <section className="panel processing">
          <h2>Extracting bid brief</h2>
          <p className="panel-lead">
            Turning the tender PDF into eligibility, commercial terms, BOQ, and
            a document checklist.
          </p>
          <div className="progress-wrap">
            <div className="progress-label">
              <span>{processMsg}</span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        </section>
      )}

      {stage === "brief" && brief && (
        <BriefView
          brief={brief}
          tab={tab}
          onTab={setTab}
          onReset={() => {
            setBrief(null);
            setStage("landing");
          }}
        />
      )}
    </div>
  );
}

function BriefView({
  brief,
  tab,
  onTab,
  onReset,
}: {
  brief: TenderBrief;
  tab: BriefTab;
  onTab: (t: BriefTab) => void;
  onReset: () => void;
}) {
  const signalTitle =
    brief.bidSignal === "bid"
      ? "Proceed to price"
      : brief.bidSignal === "caution"
        ? "Bid with caution"
        : "Likely no-bid";

  const boqTotal = brief.boq.reduce(
    (sum, row) => sum + (row.estimatedRate ?? 0) * row.qty,
    0,
  );

  return (
    <div>
      <div className="brief-header">
        <section className="panel" style={{ marginTop: 0 }}>
          <p className="panel-lead" style={{ marginBottom: "0.35rem" }}>
            {brief.fileName} · {brief.tenderNo}
          </p>
          <h2>{brief.title}</h2>
          <p className="panel-lead">
            {brief.authority} · {brief.location} · {brief.workType}
          </p>
          <div className="stat-grid">
            <div className="stat">
              <span>Estimated cost</span>
              <strong>₹{brief.estimatedCostCr} Cr</strong>
            </div>
            <div className="stat">
              <span>EMD</span>
              <strong>₹{brief.emdLakh} Lakh</strong>
            </div>
            <div className="stat">
              <span>Bid deadline</span>
              <strong>{brief.bidDeadline}</strong>
            </div>
            <div className="stat">
              <span>Completion</span>
              <strong>{brief.completionMonths} months</strong>
            </div>
          </div>
        </section>
        <aside className={`signal ${brief.bidSignal}`}>
          <div className="signal-label">Bid signal</div>
          <h3>{signalTitle}</h3>
          <p>{brief.bidSignalReason}</p>
        </aside>
      </div>

      <div className="tabs" role="tablist" aria-label="Brief sections">
        {(
          [
            ["overview", "Commercial & risks"],
            ["eligibility", "Eligibility"],
            ["boq", "BOQ extract"],
            ["documents", "Documents"],
            ["actions", "Before you bid"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`tab${tab === id ? " active" : ""}`}
            onClick={() => onTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="two-col">
          <section className="panel">
            <h2>Commercial terms</h2>
            <p className="panel-lead">
              What the contractor checks before opening the rate sheet.
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Term</th>
                    <th>Extracted value</th>
                  </tr>
                </thead>
                <tbody>
                  {brief.commercial.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td>{row.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="panel">
            <h2>Risk flags</h2>
            <p className="panel-lead">
              Items that change margin, cash, or schedule risk.
            </p>
            <ul className="list-clean">
              {brief.risks.map((risk) => (
                <li key={risk.title} className={risk.level}>
                  <strong>
                    <span className={`badge ${risk.level}`}>{risk.level}</span>{" "}
                    {risk.title}
                  </strong>
                  <span>{risk.detail}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}

      {tab === "eligibility" && (
        <section className="panel">
          <h2>Eligibility vs your profile</h2>
          <p className="panel-lead">
            Prototype compares against a sample Class-A electrical contractor
            profile.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Criterion</th>
                  <th>Required</th>
                  <th>Status</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {brief.eligibility.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{row.required}</td>
                    <td>
                      <span className={`badge ${row.status}`}>{row.status}</span>
                    </td>
                    <td>{row.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "boq" && (
        <section className="panel">
          <h2>BOQ extract</h2>
          <p className="panel-lead">
            Line items pulled from the schedule of quantities. Estimated rates
            are starter library rates for planning — not the bid.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Description</th>
                  <th>Unit</th>
                  <th>Qty</th>
                  <th>Library rate</th>
                  <th>Amount</th>
                </tr>
              </thead>
              <tbody>
                {brief.boq.map((row) => (
                  <tr key={row.sno}>
                    <td>{row.sno}</td>
                    <td>{row.description}</td>
                    <td>{row.unit}</td>
                    <td>{row.qty}</td>
                    <td>
                      {row.estimatedRate != null
                        ? formatInr(row.estimatedRate)
                        : "—"}
                    </td>
                    <td>
                      {row.estimatedRate != null
                        ? formatInr(row.estimatedRate * row.qty)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="footer-note">
            Rough library total: <strong>{formatInr(boqTotal)}</strong> (before
            overhead, finance cost, contingency, profit).
          </p>
        </section>
      )}

      {tab === "documents" && (
        <section className="panel">
          <h2>Document pack</h2>
          <p className="panel-lead">
            Everything that must be ready on IREPS before the deadline.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Status</th>
                  <th>Next step</th>
                </tr>
              </thead>
              <tbody>
                {brief.documents.map((doc) => (
                  <tr key={doc.name}>
                    <td>{doc.name}</td>
                    <td>
                      <span className={`badge ${doc.status}`}>{doc.status}</span>
                    </td>
                    <td>{doc.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "actions" && (
        <section className="panel actions">
          <h2>Before you bid — contractor checklist</h2>
          <p className="panel-lead">
            The practical sequence after reading the PDF, matching what your
            father&apos;s network actually does on the ground.
          </p>
          <ol>
            {brief.contractorActions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
          <div className="cta-row" style={{ marginTop: "1.25rem" }}>
            <button type="button" className="btn btn-primary" onClick={onReset}>
              Analyze another tender
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
