# Breathe ESG — Emissions Ingestion & Audit Platform

> **Breathe ESG Tech Intern Assignment — May 2026**  
> A multi-tenant, audit-ready GHG emissions ingestion and review platform.  
> **Live Demo:** [https://breathe-esg-project.netlify.app](https://breathe-esg-project.netlify.app)

---

## What This Is

Breathe ESG is a prototype emissions data management platform built to solve one specific problem: **companies have ESG data spread across SAP, utility portals, and travel systems. None of it is GHG Protocol-aligned. Someone has to normalize it, flag anomalies, get a human to sign off, and produce an audit-ready output.**

This prototype handles that entire pipeline end-to-end:
1. **Ingest** raw data (SAP OData V2, Utility CSV, Concur/Navan CSV).
2. **Normalize** units, fuels, and distances.
3. **Calculate** emissions using DEFRA 2023 and CEA 2022-23 factors.
4. **Flag** anomalies (unusual spikes, unknown plants, data entry errors).
5. **Review** via an interactive dashboard.
6. **Export** a locked, immutable, auditor-ready CSV.

---

## Live Demo Credentials

The prototype features strict multi-tenancy. Two separate test tenants exist:

| Tenant | Role | Username | Password | Notes |
|--------|------|----------|----------|-------------|
| **Acme Industries** | Analyst | `analyst` | `breathe2026` | Contains pre-existing test data |
| **Beta Corp** | Reviewer | `reviewer` | `breathe2026` | Starts completely empty |

*Try uploading the mock data files located in `backend/mock_data/` to test the pipeline.*

---

## Key Design Documents

I strongly recommend reading these four documents to understand the architecture, the decisions made, and the deliberate tradeoffs:

1. **[`MODEL.md`](MODEL.md)** — Full schema documentation, tenant isolation strategy, and the "two-layer storage" audit principle.
2. **[`SOURCES.md`](SOURCES.md)** — Specifications for SAP, Utility, and Travel sources, emission factor citations, and mock data explanations.
3. **[`DECISIONS.md`](DECISIONS.md)** — Resolved ambiguities, chosen standards, and questions I would ask a PM.
4. **[`TRADEOFFS.md`](TRADEOFFS.md)** — Deliberate cuts (e.g., OData V2 only, static factors, no RBAC) made to fit the prototyping timeline.

---

## Tech Stack

- **Backend:** Django 5.2 + Django REST Framework + SQLite (Local) / PostgreSQL (Prod)
- **Frontend:** React 18 + Vite + Vanilla CSS
- **Deployment:** Render (Backend) + Netlify (Frontend)

---

## Running Locally

**Backend:**
```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp ../.env.example .env
python manage.py migrate
python manage.py seed  # Idempotent tenant creation
python manage.py runserver 0.0.0.0:8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```
