# BidBrief

**Tender PDF → bid-ready brief** for Indian Railways electrical / TRD contractors.

Prototype for a pre-bid workflow: eligibility, commercial terms, risk flags, BOQ extract, and document checklist — before anyone opens a full rate sheet.

## Why this exists

A contractor receiving an NIT PDF typically:

1. Screens bid / no-bid
2. Extracts EMD, LD, payment, PVC
3. Checks eligibility & OEM letters
4. Pulls BOQ into Excel
5. Assembles IREPS document pack

BidBrief compresses steps 1–5 into one brief.

## Run locally

```bash
cd bidbrief
npm install
npm run dev
```

Open the URL Vite prints (default `http://localhost:5174`).

## What’s in the MVP

| Screen | Purpose |
|--------|---------|
| Landing | Brand + CTA |
| Upload | Drop NIT PDF (demo uses sample) |
| Extract | Simulated parse pipeline |
| Brief | Bid signal, commercial, risks, eligibility, BOQ, docs, actions |

Sample tender: Western Railway TRD — Valsad TSS 25kV OHE switching (`WR/EL/TRD/2026/118`).

## Not in v0 (next)

- Real PDF / OCR extraction (IREPS NITs)
- Contractor profile store (turnover, licenses, past works)
- Live material rate library
- Multi-user workspace for estimating teams
- Export to Excel + IREPS checklist PDF

## Product wedge

Sell first to **electrical contractors who bid railway TRD / general electrical works**, via personal networks (site engineers, JE/SSE contacts, contractor associations). Charge per tender analyzed or a small monthly seat fee.
