export type RiskLevel = "high" | "medium" | "low";
export type DocStatus = "ready" | "missing" | "expiring";
export type BidSignal = "bid" | "caution" | "no-bid";

export interface TenderBrief {
  fileName: string;
  title: string;
  authority: string;
  tenderNo: string;
  location: string;
  estimatedCostCr: number;
  emdLakh: number;
  bidDeadline: string;
  completionMonths: number;
  workType: string;
  bidSignal: BidSignal;
  bidSignalReason: string;
  eligibility: {
    label: string;
    required: string;
    status: "pass" | "fail" | "check";
    note: string;
  }[];
  commercial: {
    label: string;
    value: string;
  }[];
  risks: {
    level: RiskLevel;
    title: string;
    detail: string;
  }[];
  boq: {
    sno: number;
    description: string;
    unit: string;
    qty: number;
    estimatedRate: number | null;
  }[];
  documents: {
    name: string;
    status: DocStatus;
    note: string;
  }[];
  contractorActions: string[];
}

export const SAMPLE_TENDER: TenderBrief = {
  fileName: "NIT_WR_EL_TRD_2026_118.pdf",
  title:
    "Supply, erection, testing & commissioning of 25kV OHE switching equipment and associated cabling at Valsad TSS",
  authority: "Western Railway — Electrical (TRD)",
  tenderNo: "WR/EL/TRD/2026/118",
  location: "Valsad TSS, Gujarat",
  estimatedCostCr: 4.85,
  emdLakh: 9.7,
  bidDeadline: "2026-04-28 15:00 IST",
  completionMonths: 9,
  workType: "Railway electrical / TRD",
  bidSignal: "caution",
  bidSignalReason:
    "Eligible on paper, but completion period is tight and LD is steep. Confirm gang + outage window before bidding.",
  eligibility: [
    {
      label: "Average annual turnover (last 3 yrs)",
      required: "≥ ₹2.5 Cr",
      status: "pass",
      note: "Your profile: ₹3.1 Cr",
    },
    {
      label: "Similar work experience",
      required: "1 work ≥ ₹2.0 Cr in OHE/TRD in last 7 yrs",
      status: "check",
      note: "Need completion certificate for Surat TSS feeder job",
    },
    {
      label: "Electrical contractor license",
      required: "Class A / equivalent valid",
      status: "pass",
      note: "Valid till Aug 2027",
    },
    {
      label: "OEM authorization",
      required: "For interrupters & control gear as per RDSO list",
      status: "fail",
      note: "Missing — request from approved vendor this week",
    },
  ],
  commercial: [
    { label: "Tender type", value: "Open, item-rate (IREPS)" },
    { label: "EMD", value: "₹9.7 Lakh (online / BG)" },
    { label: "Security deposit", value: "5% of contract value" },
    { label: "Retention", value: "5% from R/A bills" },
    { label: "Payment", value: "R/A bills monthly; 45–60 day typical" },
    { label: "GST", value: "Extra as applicable" },
    { label: "Price variation", value: "Not payable on major bought-outs" },
    { label: "LD / penalty", value: "0.5% per week, max 10%" },
    { label: "Defect liability", value: "24 months from commissioning" },
    { label: "Bid validity", value: "90 days" },
  ],
  risks: [
    {
      level: "high",
      title: "No PVC on copper / switchgear",
      detail:
        "Cable and interrupter prices can move 8–12%. Lock supplier quotes with validity past bid date.",
    },
    {
      level: "high",
      title: "Traffic / power block dependency",
      detail:
        "Erection needs approved blocks. Idle gang cost if blocks slip — build contingency in rates.",
    },
    {
      level: "medium",
      title: "Aggressive 9-month completion",
      detail:
        "Long-lead RDSO items + monsoon window. Confirm OEM delivery before quoting margin.",
    },
    {
      level: "medium",
      title: "Measurement disputes on cabling",
      detail:
        "BOQ says ‘as per site’. Joint measurement protocol must be clear in kickoff.",
    },
    {
      level: "low",
      title: "Document format on IREPS",
      detail: "Affidavits must be notarized PDF under 5 MB each.",
    },
  ],
  boq: [
    {
      sno: 1,
      description: "25kV interrupter, RDSO approved make, supply",
      unit: "Nos",
      qty: 4,
      estimatedRate: 1850000,
    },
    {
      sno: 2,
      description: "Control & relay panel for switching post",
      unit: "Set",
      qty: 1,
      estimatedRate: 920000,
    },
    {
      sno: 3,
      description: "XLPE 25kV cable, 1×300 sq.mm",
      unit: "m",
      qty: 850,
      estimatedRate: 2450,
    },
    {
      sno: 4,
      description: "Cable laying in trench incl. sand, bricks, backfill",
      unit: "m",
      qty: 850,
      estimatedRate: 420,
    },
    {
      sno: 5,
      description: "Erection, testing & commissioning of interrupters",
      unit: "Nos",
      qty: 4,
      estimatedRate: 95000,
    },
    {
      sno: 6,
      description: "Earthing stations & bonding as per Spec EL/OHE",
      unit: "Nos",
      qty: 12,
      estimatedRate: 18500,
    },
    {
      sno: 7,
      description: "Temporary lighting / site facilities during blocks",
      unit: "LS",
      qty: 1,
      estimatedRate: 175000,
    },
  ],
  documents: [
    {
      name: "GST registration & PAN",
      status: "ready",
      note: "On file",
    },
    {
      name: "CA turnover certificate (3 years)",
      status: "ready",
      note: "FY22–FY25",
    },
    {
      name: "Similar work completion certificate",
      status: "missing",
      note: "Request from DRM/EL office",
    },
    {
      name: "OEM authorization — interrupters",
      status: "missing",
      note: "Critical path for bid",
    },
    {
      name: "Electrical contractor license",
      status: "ready",
      note: "Upload notarized copy",
    },
    {
      name: "Bid security / EMD proof",
      status: "missing",
      note: "Arrange BG by 24 Apr",
    },
    {
      name: "Integrity pact & affidavits",
      status: "expiring",
      note: "Template ready; re-sign with tender no.",
    },
    {
      name: "MSME / Udyam (if claiming preference)",
      status: "ready",
      note: "Optional for this NIT",
    },
  ],
  contractorActions: [
    "Confirm OEM delivery lead time for 25kV interrupters (RDSO list)",
    "Get written quote validity ≥ 100 days on cable + switchgear",
    "Call SSE/TRD Valsad for typical block availability",
    "Retrieve Surat TSS completion certificate scan",
    "Decide bid margin after idle-time contingency (suggest 4–6%)",
    "Fill IREPS BOQ carefully — units are Nos/m/Set/LS",
  ],
};

export function formatInr(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}
