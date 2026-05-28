# Breathe ESG — Emissions Ingestion & Audit Platform

> **Breathe ESG Tech Intern Assignment — May 2026**  
> A multi-tenant, audit-ready GHG emissions ingestion and review platform.  
> Ingest from SAP OData, utility billing portals, and corporate travel systems. Normalize, flag, review, approve, and export — all in one pipeline.

---

## Table of Contents

1. [What This Is](#what-this-is)
2. [Live Demo Credentials](#live-demo-credentials)
3. [Pipeline Architecture](#pipeline-architecture)
4. [Data Model in Brief](#data-model-in-brief)
5. [Scope Classification Logic](#scope-classification-logic)
6. [Project Structure](#project-structure)
7. [Running Locally](#running-locally)
8. [Testing the Full Flow](#testing-the-full-flow)
9. [Audit Export](#audit-export)
10. [Key Design Documents](#key-design-documents)
11. [Deliberate Tradeoffs](#deliberate-tradeoffs)

---

## What This Is

Breathe ESG is a prototype emissions data management platform built to solve one specific problem: **companies have ESG data spread across SAP, utility portals, and travel systems. None of it is GHG Protocol-aligned. Someone has to normalize it, flag anomalies, get a human to sign off, and produce an audit-ready output.**

This prototype handles that entire pipeline end-to-end:

```
Raw source data (SAP / Utility CSV / Travel CSV)
        ↓
Ingestion + deduplication (source_row_hash)
        ↓
Normalization (units → kWh, distances → km, fuels → liters)
        ↓
Emission calculation (DEFRA 2023 / CEA 2022-23 factors)
        ↓
Anomaly flagging (suspicious records with human-readable reasons)
        ↓
Analyst review dashboard (approve / reject / bulk actions)
        ↓
Audit lock (is_locked=True, immutable after approval)
        ↓
CSV export (Scope-ordered, fully traceable, auditor-ready)
```

**What makes this different from just running a spreadsheet macro:**

- Every record carries an unbroken audit trail from source row → raw storage → normalization → approval → lock
- The same analyst action that approves a record locks it — you cannot approve without locking
- The export file is not a summary; it is a row-level disclosure with emission factor source, reviewer identity, and source row hash on every line
- Multi-tenancy is built in from the schema up — two tenants share one database with zero data leakage

---

## Live Demo Credentials

Two isolated tenants. Both start empty. Each sees only their own data.

| Tenant | Role | Username | Password | Start State |
|--------|------|----------|----------|-------------|
| **Acme Industries** | Analyst | `analyst` | `breathe2026` | Pre-populated with test data (SAP, utility, travel) |
| **Beta Corp** | Reviewer | `reviewer` | `breathe2026` | Completely empty — ingest fresh |

**Reviewer flow (Beta Corp):**
1. Log in as `reviewer / breathe2026`
2. Upload a utility CSV → see records appear in the dashboard
3. Upload a travel CSV → see those records appear
4. Trigger the SAP ingestion → see SAP records appear
5. Review, approve, lock records
6. Click **Export Approved** → download the audit-ready CSV
7. Log out, log in as `analyst / breathe2026` → see Acme's completely separate data

---

## Pipeline Architecture

### Ingestion Layer

Three source types, each with its own raw storage table:

**SAP — Scope 1 (Stationary Combustion)**
- Simulates an SAP OData V2 `/PurchaseOrderSet` feed
- Parses `/Date(ms)/` timestamps, maps plant codes via `PlantLookup`
- Fuel types: Diesel (FUEL01), Petrol (FUEL02), LPG (FUEL03)
- DEFRA 2023 emission factors: Diesel 2.64 kg CO₂e/L, Petrol 2.31 kg CO₂e/L, LPG 1.55 kg CO₂e/kg

**Utility Billing — Scope 2 (Purchased Electricity)**
- Accepts CSV exports from BESCOM, MSEDCL, TGSPDCL, APSPDCL
- Handles meter constants (CT metered industrial connections)
- Majority-month billing period attribution for cross-month cycles
- CEA 2022-23 factor: 0.716 kg CO₂e/kWh (national grid average)
- Flags: zero consumption, meter reset (present < previous), estimated readings

**Corporate Travel — Scope 3 (Business Travel)**
- Accepts Concur / Navan CSV exports
- Three sub-types: flights, hotel stays, ground transport
- Flights: IATA origin+destination → distance lookup → DEFRA 2023 (with radiative forcing)
- Hotels: rooms × nights × country emission factor
- Ground: distance × mode factor (car/taxi/train/bus), scope by provider_type (company = Scope 1, third-party = Scope 3)

### Normalization Layer

Each normalizer produces a `NormalizedEmissionRecord` dict with:
- Canonical quantity + unit
- CO₂e in kg (or tonnes for SAP — stored as kg throughout)
- Emission factor + source citation
- Status: `pending` / `suspicious` / `approved` / `rejected`
- `source_row_hash` — SHA-256 of the original row for deduplication

### Review Dashboard

- Summary strip: total CO₂e by scope, pending/suspicious/approved/rejected counts
- Per-row: full audit details in a slide-in drawer (source → raw → normalized → approval)
- Suspicious records: expandable warning with the exact flag reason from the normalizer
- Bulk approve: select multiple pending records, approve in one action
- Batch history sidebar: last 20 ingestion batches across all sources with row counts and success rates

### Audit Lock + Export

Approving a record sets `status=approved` **and** `is_locked=True` in a single atomic write. Locked records cannot be modified. The export filters `status=approved AND is_locked=True` — both conditions must be true.

Export columns: GHG Category, Scope, Activity, Date, Reporting Month, Quantity (Original), Unit (Original), Quantity (Normalized), Unit (Normalized), CO₂e (kg), Emission Factor, Factor Source, Status, Reviewed By, Reviewed At, Raw Record Type, Raw Record ID, Source Row Hash.

---

## Data Model in Brief

Two-layer storage is the core design principle. Every ingestion writes two records:

1. **Raw record** — stores the source data exactly as received, never modified
2. **NormalizedEmissionRecord** — stores the canonical, comparable output

The raw layer is the audit foundation. If normalization logic changes (updated emission factor, corrected unit conversion), reprocessing runs against the raw layer — the original source is always recoverable.

All three sources write into **one** `NormalizedEmissionRecord` table. `source_type` identifies the origin. A generic FK (`raw_record_id` + `raw_record_type`) points back to whichever raw table produced it. This makes cross-source Scope 1+2+3 totals possible without UNION queries.

```
Tenant
  ├── UserProfile (1:1 → Django User)
  ├── PlantLookup (plant_code → location, region)
  │
  ├── SAPIngestionBatch → RawSAPRecord → NormalizedEmissionRecord
  ├── UtilityIngestionBatch → RawUtilityRecord → NormalizedEmissionRecord
  └── TravelIngestionBatch → RawTravelRecord → NormalizedEmissionRecord
```

Full schema documentation: [`MODEL.md`](MODEL.md)

---

## Scope Classification Logic

| Source | Activity | Scope | Rationale |
|--------|----------|-------|-----------|
| SAP | Diesel/Petrol/LPG combustion | Scope 1 | Direct combustion, company-owned asset |
| Utility | Grid electricity | Scope 2 | Purchased energy, company does not own generation |
| Travel — Flight | Air travel | Scope 3 Cat. 6 | Third-party carrier |
| Travel — Hotel | Hotel stays | Scope 3 Cat. 6 | Third-party property |
| Travel — Ground (company vehicle) | Car, van | Scope 1 | Company-owned vehicle, direct combustion |
| Travel — Ground (third-party) | Taxi, train, bus, Uber | Scope 3 | Purchased transport service |

Ground transport scope is determined by `provider_type`, not `expense_type` — two rows that both say "ground" can land in different scopes based on who owns the vehicle.

---

## Project Structure

```
breathe-esg/
├── backend/                        # Django + DRF API
│   ├── config/                     # Settings, URLs, WSGI
│   ├── core/                       # Tenant, UserProfile models
│   ├── ingestion/
│   │   ├── models.py               # All raw + normalized tables
│   │   ├── serializers.py          # DRF serializers
│   │   ├── views.py                # Ingest, review, export endpoints
│   │   ├── urls.py                 # API routes
│   │   ├── normalizers/
│   │   │   ├── sap.py              # SAP OData normalization
│   │   │   ├── utility.py          # Electricity billing normalization
│   │   │   ├── travel.py           # Flight / hotel / ground normalization
│   │   │   └── constants.py        # Emission factors (DEFRA 2023, CEA 2022-23)
│   │   └── management/commands/
│   │       └── seed.py             # Tenant + user setup (idempotent)
│   ├── mock_data/                  # Test CSVs (send separately to reviewers)
│   │   ├── sap/
│   │   ├── utility/
│   │   └── travel/
│   └── requirements.txt
│
├── frontend/                       # React + Vite SPA
│   ├── src/
│   │   ├── components/
│   │   │   ├── LoginPage.jsx
│   │   │   ├── IngestPage.jsx      # Upload UI for all three sources
│   │   │   ├── ReviewDashboard.jsx # Main analyst view
│   │   │   ├── RecordsTable.jsx    # Sortable, filterable, selectable table
│   │   │   ├── RecordDetailDrawer.jsx # Full audit trail slide-in
│   │   │   ├── FailedRowsPanel.jsx # Failed ingestion rows with reasons
│   │   │   ├── BatchHistory.jsx    # Ingestion batch sidebar
│   │   │   └── FilterBar.jsx       # Status/scope/source filters
│   │   ├── api.js                  # All fetch calls + auth headers
│   │   └── index.css               # Design system
│   └── package.json
│
├── MODEL.md                        # Full data model documentation
├── SOURCES.md                      # Data source specs + emission factors
├── TRADEOFFS.md                    # What was not built and why
├── DECISIONS.md                    # Unanswered PM questions
├── REVIEW_PREP.md                  # Expected review questions + answers
└── README.md                       # This file
```

---

## Running Locally

### Prerequisites

- Python 3.11+
- Node.js 18+
- Git

### Backend setup

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt

# Copy environment config
cp ../.env.example .env
# Edit .env — set SECRET_KEY, leave DATABASE_URL as sqlite:///db.sqlite3 for local

python manage.py migrate
python manage.py seed          # Creates Acme + Beta Corp tenants and users

python manage.py runserver 0.0.0.0:8000
```

> **Note:** `seed.py` is fully idempotent — running it twice will not duplicate tenants or users. Use `python manage.py seed --clear` only in local development to wipe and re-seed ingestion records. **Never run `--clear` on a deployed instance.**

### Frontend setup

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

The frontend proxies all `/api/` requests to `http://localhost:8000` via Vite's dev proxy.

---

## Testing the Full Flow

Mock CSV files are in `backend/mock_data/`. Use these to populate the dashboard with realistic data including normal, suspicious, and failed records.

### Utility uploads (Scope 2)

| File | What it tests |
|------|---------------|
| `utility_normal.csv` | Clean records — all should normalize to `pending` |
| `utility_suspicious.csv` | Estimated meter readings → `suspicious` |
| `utility_billing_misalignment.csv` | Cross-month billing periods → majority-month logic |
| `utility_multi_meter.csv` | Multiple meters from the same account |
| `utility_mixed_outcomes.csv` | Mix of normal, suspicious, and failed rows |
| `utility_edge_cases.csv` | Zero consumption (failure), meter reset (failure), unknown DISCOM (suspicious) |

### Travel uploads (Scope 3)

| File | What it tests |
|------|---------------|
| `travel_normal_flights.csv` | Clean domestic flights — all `pending` |
| `travel_flagged.csv` | Missing IATA codes, cancelled bookings, invalid dates → failures |
| `travel_cabin_mix.csv` | Economy, business, first class — tests EF differentiation |
| `travel_hotels.csv` | Hotel stays with known + unknown country codes |
| `travel_ground_mix.csv` | Car (Scope 1), taxi, train (Scope 3) |
| `travel_suspicious_mix.csv` | Blank cabin class (suspicious), voided booking (failure), zero-night hotel |
| `travel_comprehensive.csv` | All failure types in one file |

### SAP trigger (Scope 1)

Use the dropdown on the Ingest page:
- **Generate fresh data** — random fuel purchase orders across plants
- **Test: Unknown plant codes** — plant codes not in `PlantLookup` → suspicious
- **Test: High quantity** — unusually large purchase orders → suspicious

### Review workflow

1. Upload files from each source
2. Go to **Review Dashboard**
3. Filter by `suspicious` — investigate flagged records using the ⚠ popover
4. Click any row for the full audit trail in the detail drawer
5. Approve clean records individually or bulk-select + bulk approve
6. Click **Export Approved** — downloads `emissions_inventory_{tenant}.csv`

---

## Audit Export

The export is ordered Scope 1 → Scope 2 → Scope 3, then by source and date within each scope. Every row includes:

- **GHG Category** — e.g. "Scope 1 — Stationary Combustion"
- **Emission Factor** — exact value used in calculation
- **Factor Source** — e.g. "DEFRA 2023 — long haul, business (with RF)"
- **Reviewed By** — username of the analyst who approved
- **Reviewed At** — ISO timestamp of approval
- **Source Row Hash** — SHA-256 of the original source row (tamper evidence)
- **Raw Record ID** — FK back to the raw table for traceability

The math on every row is independently verifiable: `Quantity (Normalized) × Emission Factor = CO₂e (kg)`.

---

## Key Design Documents

| Document | Purpose |
|----------|---------|
| [`MODEL.md`](MODEL.md) | Full schema: every table, every field, every design decision |
| [`SOURCES.md`](SOURCES.md) | Data source specifications, emission factor citations, normalizer logic |
| [`TRADEOFFS.md`](TRADEOFFS.md) | Three deliberate cuts: OData V2 only, static factors, no RBAC |
| [`DECISIONS.md`](DECISIONS.md) | Open questions — what would be asked of the PM before building further |
| [`REVIEW_PREP.md`](REVIEW_PREP.md) | Expected review questions and how to answer them |

---

## Deliberate Tradeoffs

Three things were deliberately not built. Each is documented in [`TRADEOFFS.md`](TRADEOFFS.md).

**1. SAP: OData V2 only**
SAP S/4HANA Cloud uses OData V4 with ISO 8601 dates. The current `/Date(ms)/` parser would produce null dates on an S/4HANA response. Clients without SAP Gateway configured cannot use this path at all.

**2. Static emission factors**
All factors are hardcoded constants in `normalizers/constants.py`. CEA publishes updated grid factors annually. There is no reprocessing pipeline — historical records cannot be updated when factors change without a separate backfill operation.

**3. No RBAC**
One user type. The analyst who ingests data can approve their own records. This is a known separation-of-duties gap. Most ESG assurance frameworks (GHG Protocol, ISO 14064) require that input and sign-off are performed by different people.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | Django 5.2 + Django REST Framework |
| Auth | DRF Token Authentication |
| Database | SQLite (local) / PostgreSQL (production via Render) |
| Frontend | React 18 + Vite |
| Styling | Vanilla CSS (no framework) |
| Deployment | Render (backend) + Render Static Sites (frontend) |

---

## Emission Factor Sources

| Factor | Source | Year | Value |
|--------|--------|------|-------|
| Diesel | DEFRA Conversion Factors | 2023 | 2.6395 kg CO₂e/L |
| Petrol | DEFRA Conversion Factors | 2023 | 2.3124 kg CO₂e/L |
| LPG | DEFRA Conversion Factors | 2023 | 1.5543 kg CO₂e/kg |
| Grid electricity (IN) | CEA Grid Emission Factor | 2022-23 | 0.716 kg CO₂e/kWh |
| Flights (economy, short) | DEFRA Aviation Factors | 2023 | 0.2554 kg CO₂e/pkm (with RF) |
| Flights (business, long) | DEFRA Aviation Factors | 2023 | 0.8154 kg CO₂e/pkm (with RF) |
| Hotel (IN) | Defra / BEIS default | 2023 | 22.08 kg CO₂e/room-night |

Radiative forcing is included in DEFRA flight factors. `RADIATIVE_FORCING_INCLUDED = True` is documented in `constants.py` — do not apply an additional multiplier.

Full factor citations: [`SOURCES.md`](SOURCES.md)
