# DATA MODEL

## Breathe ESG — Emissions Ingestion Platform
**Client:** Acme Industries | **Intern Assignment** | May 2026

---

## Core Design Principles

Two principles are non-negotiable and every table in this model exists to serve them.

**Principle 1 — Two-layer storage always.**
Every ingestion creates two records: a Raw record that stores the source data exactly as it arrived, and a NormalizedEmissionRecord that stores the canonical, comparable output. Raw records are never modified. If normalization logic changes (new emission factor, corrected unit conversion), I reprocess from raw — the original source is always recoverable. This is what lets an auditor ask "where did this number come from" and get a truthful answer.

**Principle 2 — One unified normalized table.**
All three sources — SAP fuel procurement, utility electricity, corporate travel — write into a single `NormalizedEmissionRecord` table. A `source_type` field identifies the origin. A generic FK (`raw_record_id` + `raw_record_type`) points back to whichever raw table produced it. This is what makes cross-source reporting (Scope 1 + 2 + 3 totals, comparisons over time) possible without UNION queries or application-side joins.

**Principle 3 — Tenant isolation at every layer.**
The system is multi-tenant from the ground up, designed to run multiple clients securely within a single database instance (such as my single Render PostgreSQL instance). Every data-bearing table carries a `tenant` FK. The `_get_tenant(request)` helper resolves the authenticated user's tenant on every API call via `UserProfile`, and every queryset filters by that tenant before any other condition is applied. No query touches rows from another tenant. 

For the prototype deployment, I have implemented exactly two isolated tenants:
* **Acme Industries** (associated with the `analyst` user account)
* **Beta Corp** (associated with the `reviewer` user account)

Row-level separation guarantees that the `analyst` and `reviewer` can only query and modify data for their respective companies, with zero cross-tenant data leakage.

---

## Entity Map

```
Tenant
  ├── UserProfile (1:1 → User)
  ├── PlantLookup (plant_code → location + region)
  │
  ├── SAPIngestionBatch
  │     └── RawSAPRecord (M → 1 batch)
  │           └── NormalizedEmissionRecord (1 → 1 raw)
  │
  ├── UtilityIngestionBatch
  │     └── RawUtilityRecord (M → 1 batch)
  │           └── NormalizedEmissionRecord (1 → 1 raw)
  │
  └── TravelIngestionBatch
        └── RawTravelRecord (M → 1 batch)
              └── NormalizedEmissionRecord (1 → 1 raw)
```

---

## Tables

### Client Isolation Boundary — `core_tenant`

The top-level isolation boundary. Every queryable object in the system carries a `tenant` FK. No query ever runs without filtering by tenant. This is the multi-tenancy scaffold.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| name | CharField(200) | e.g. "Acme Industries" |
| slug | SlugField(100) | e.g. "acme" — used in URLs and seed |
| created_at | DateTimeField | auto |

Every data-bearing table carries a `tenant` FK. All querysets are scoped by tenant — the `_get_tenant(request)` helper resolves the authenticated user's tenant via `UserProfile`, and every view filters against it before returning data. In my Render deployment, a single PostgreSQL database serves both the `Acme Industries` (`analyst`) and `Beta Corp` (`reviewer`) tenants with strict row-level isolation.

---

### User-to-Tenant Link — `core_userprofile`

This table acts as the association bridge linking Django's built-in authentication system with my multi-tenant boundary. Each database user is assigned to exactly one tenant profile to enforce strict row-level query isolation during API requests.

| Field | Type | Notes |
|-------|------|-------|
| user | OneToOneField(User) | on_delete=CASCADE |
| tenant | ForeignKey(Tenant) | on_delete=CASCADE |

**Why `on_delete=CASCADE` is used here:**
* Deleting a Django user automatically cleans up their profile to prevent orphaned link records.
* Deleting a Tenant automatically dissolves all associated profiles to prevent unauthorized access.

---

### SAP Plant Code LookUp Table — `ingestion_plantlookup`

SAP plant codes are opaque identifiers (1010, 2030, 3050). Without a lookup table, I cannot determine the geographic region for an emission record, which affects the emission factor applied for electricity and is required for audit reporting.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| tenant | FK(Tenant) | |
| plant_code | CharField(20) | e.g. "1010" |
| plant_name | CharField(200) | e.g. "Mumbai Factory" |
| country_code | CharField(10) | "IN" |
| region | CharField(100) | "Maharashtra" |

Three plant codes are pre-loaded for Acme Industries: 1010 (Mumbai Factory, Maharashtra), 2030 (Delhi Warehouse, Delhi), 3050 (Chennai Plant, Tamil Nadu). These represent the three facility locations present in the SAP mock data. The SAP normalizer looks up the incoming `plant_code` from each purchase order against this table at normalization time — if the code resolves, the plant name and region are written into `activity_description` on the normalized record. If it does not resolve, the record is flagged as suspicious because geographic attribution is missing.

---

### SAP Ingestion Run Header — `ingestion_sapingestionbatch`

One batch per SAP trigger call. Tracks the simulation scenario (e.g., dynamic generator, or specific plant-error/quantity-error testing payloads), and carries top-level status and counts for operational visibility.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| tenant | FK(Tenant) | |
| ingestion_source | CharField(200) | "dynamic_generator" or simulation payload name (e.g. "sap_high_quantity.json") |
| status | CharField | processing / done / failed |
| raw_payload | JSONField | entire OData response stored verbatim |
| rows_total | IntegerField | |
| rows_failed | IntegerField | default 0 |
| created_at | DateTimeField | auto |

`raw_payload` stores the entire OData JSON as received. This is the source-of-truth for "what did SAP actually send me." If a normalizer bug is found later, I can reprocess from this field without re-triggering the SAP endpoint.

---

### SAP Purchase Order Lines, As Received — `ingestion_rawsaprecord`

One row per purchase order line item in the SAP OData response. Fields are named to match the OData V2 column names exactly — no translation at this layer.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| batch | FK(SAPIngestionBatch) | on_delete=CASCADE |
| tenant | FK(Tenant) | denormalized for query performance |
| purchase_order | CharField(20) | PO number, e.g. "4512345678" |
| purchase_order_item | CharField(10) | line item, e.g. "00010" |
| company_code | CharField(10) | SAP company code |
| plant_code | CharField(20) | resolved via PlantLookup |
| material | CharField(50) | material number |
| material_group | CharField(20) | FUEL01–FUEL04 — determines fuel type |
| order_quantity | DecimalField(15,3) | as-received quantity |
| quantity_unit | CharField(10) | as-received unit: L, GAL, KG, TO |
| document_date | DateField | parsed from /Date(ms)/ OData format |
| supplier | CharField(100) | |
| source_row_hash | CharField(64) | SHA256 of PO+item+qty+date+plant — dedup key |
| created_at | DateTimeField | auto |

`source_row_hash` is a unique SHA-256 fingerprint generated from the identifying fields of each purchase order line (plant code, material group, quantity, document date, PO number, and PO item) before the row is saved. 

During ingestion:
* The system computes this hash for each incoming purchase order row.
* It compares it against existing `RawSAPRecord` rows for that specific tenant.
* If a match is found, the duplicate row is skipped and counted as `duplicates_skipped` in the batch summary.

This deduplication mechanism prevents double-counting emissions if a user triggers the same API integration scenario multiple times within the same reporting period.

---

### Utility CSV Upload Header — `ingestion_utilityingestionbatch`

One batch per CSV upload. Stores the original filename for traceability.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| tenant | FK(Tenant) | |
| source_file_name | CharField(255) | original upload filename |
| status | CharField | processing / done / failed |
| rows_total | IntegerField | |
| rows_failed | IntegerField | default 0 |
| created_at | DateTimeField | auto |

---

### Utility Billing Lines, As Received — `ingestion_rawutilityrecord`

One row per billing line from the utility portal CSV. The 19-column schema is designed around real Indian utility bill exports — BESCOM (Karnataka), MSEDCL (Maharashtra), TGSPDCL (Telangana). Each utility uses different identifier fields for the meter account, hence the four nullable identifier columns.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| batch | FK(UtilityIngestionBatch) | |
| tenant | FK(Tenant) | |
| utility | CharField(100) | "BESCOM", "MSEDCL", "TGSPDCL", etc. |
| account_id | CharField(50) | nullable — used by some utilities |
| rr_number | CharField(50) | nullable — BESCOM-style identifier |
| consumer_number | CharField(50) | nullable — MSEDCL-style |
| usc_no | CharField(50) | nullable — TGSPDCL-style |
| consumer_name | CharField(200) | |
| tariff | CharField(50) | normalised tariff class: HT (High Tension), LT (Low Tension) |
| raw_tariff_label | CharField(200) | original label as printed on bill |
| circle_division | CharField(100) | geographic division for emission factor lookup |
| billing_period_from | DateField | nullable |
| billing_period_to | DateField | nullable |
| previous_reading | DecimalField(12,3) | kWh meter reading |
| present_reading | DecimalField(12,3) | kWh meter reading |
| units_consumed | DecimalField(12,3) | present - previous, or stated if CT metered |
| meter_constant | DecimalField(10,4) | child CT ratio multiplier (defaults to 1.0 for direct-read) |
| meter_status | CharField(50) | OK / Defective / Average |
| average_units | DecimalField(12,3) | nullable — used when meter_status != OK |
| days_in_bill_cycle | IntegerField | nullable |
| recorded_md_kw | DecimalField(10,3) | nullable — maximum demand (HT consumers) |
| source_row_hash | CharField(64) | SHA256 of utility+meter_id+period_from+period_to |
| created_at | DateTimeField | auto |

**Deduplication Hash:**
`source_row_hash` is computed as a SHA-256 fingerprint of the `utility` name, the active meter identifier (whichever of the four columns is populated), `billing_period_from`, and `billing_period_to`. This ensures that uploading the same billing cycle multiple times will not duplicate emissions data.

* **Identifier Fragmentation:** Indian DISCOMs use non-standardized account numbers (e.g., BESCOM's `rr_number`, MSEDCL's `consumer_number`, and TGSPDCL's `usc_no`). Keeping these columns separate and nullable preserves source fidelity for audit trails, but requires the normalizer to dynamically inspect and resolve the active key at runtime.
* **Geographic Factor Attribution:** Instead of applying a flat national average, the pipeline resolves the utility name to a specific state-level grid factor from the Central Electricity Authority (CEA) database (e.g., Karnataka/BESCOM: 0.82, Maharashtra/MSEDCL: 0.75, Telangana/TGSPDCL: 0.91 kg CO₂e/kWh), falling back to 0.82 kg CO₂e/kWh for unmapped utilities.
* **Billing Cycle Alignment:** Billing periods rarely match calendar months (e.g., Jan 18 to Feb 17). The normalizer resolves this by assigning a `reporting_month` using a mathematical majority-of-days rule (counting the exact number of days spent in each calendar month, with ties going to the ending month), preventing data gaps when aggregating monthly emissions.

---

### Travel Booking Segments, As Received — `ingestion_rawtravelrecord`

One row per travel booking segment. A single trip may produce multiple rows — outbound flight, return flight, hotel, ground transport on arrival. The `external_booking_id` + `segment_id` combination uniquely identifies a segment within a booking.

All three expense types (flight, hotel, ground) share this table. Columns irrelevant to a given type are null. This is a deliberate denormalization — the alternative (three separate tables) adds complexity with no query benefit for this scale.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| batch | FK(TravelIngestionBatch) | |
| tenant | FK(Tenant) | |
| expense_type | CharField(20) | flight / hotel / ground |
| source | CharField(100) | "Concur", "Navan", "manual" |
| external_booking_id | CharField(100) | booking-level identifier |
| traveler_name | CharField(200) | |
| traveler_email | CharField(254) | |
| booking_created_at | DateTimeField | nullable |
| booking_status | CharField(50) | confirmed / cancelled / modified |
| fare_amount | DecimalField(12,2) | nullable |
| currency | CharField(10) | |
| trip_id | CharField(100) | nullable — flight |
| segment_id | CharField(100) | nullable — flight |
| carrier | CharField(10) | IATA carrier code e.g. "6E" |
| flight_number | CharField(20) | |
| record_locator | CharField(20) | PNR |
| origin_iata | CharField(10) | e.g. "BOM" |
| destination_iata | CharField(10) | e.g. "DEL" |
| departure_datetime_local | DateTimeField | nullable |
| arrival_datetime_local | DateTimeField | nullable |
| cabin_class | CharField(20) | economy / business / first |
| ticket_number | CharField(30) | nullable |
| trip_type | CharField(20) | one_way / return |
| vendor_name | CharField(200) | nullable — hotel |
| city | CharField(100) | nullable — hotel |
| country_code | CharField(10) | nullable — hotel |
| check_in_date | DateField | nullable — hotel |
| check_out_date | DateField | nullable — hotel |
| nights | IntegerField | nullable — hotel |
| rooms | IntegerField | nullable — hotel |
| transport_mode | CharField(50) | nullable — ground: taxi / train / car |
| provider_type | CharField(50) | nullable — ground: company_vehicle / third_party |
| distance_km | DecimalField(10,3) | nullable — ground |
| vehicle_fuel_type | CharField(50) | nullable — ground |
| trip_date | DateField | nullable — ground |
| source_row_hash | CharField(64) | SHA256 of external_booking_id+segment_id+expense_type |
| created_at | DateTimeField | auto |

---

### The Canonical Emission Record — `ingestion_normalizedemissionrecord`

The canonical output table. Every row represents one normalized, auditable emission activity. This is what the dashboard displays. This is what goes to auditors.

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| tenant | FK(Tenant) | |
| **Source tracing** | | |
| source_type | CharField(20) | sap / utility / travel |
| raw_record_id | PositiveIntegerField | ID of the originating raw record |
| raw_record_type | CharField(30) | "RawSAPRecord" / "RawUtilityRecord" / "RawTravelRecord" |
| **Activity** | | |
| activity_date | DateField | date of the emission activity |
| reporting_month | CharField(7) | YYYY-MM — the reporting period label |
| scope | CharField(1) | 1 / 2 / 3 |
| activity_description | CharField(255) | human-readable description for analyst |
| **Quantities** | | |
| quantity_normalized | DecimalField(15,4) | in canonical unit (kWh, kg, km) |
| unit_normalized | CharField(20) | canonical unit |
| quantity_original | DecimalField(15,4) | as-received quantity |
| unit_original | CharField(20) | as-received unit |
| **Emission factor** | | |
| emission_factor | DecimalField(10,6) | kg CO₂e per unit |
| emission_factor_source | CharField(100) | "DEFRA 2023" / "CEA 2022-23" |
| co2e_kg | DecimalField(15,4) | quantity_normalized × emission_factor |
| **Review state** | | |
| status | CharField(20) | pending / suspicious / approved / rejected |
| is_locked | BooleanField | True after approval — no further edits |
| flagged_reason | TextField | populated when status=suspicious |
| reviewed_by | FK(User) | nullable, on_delete=SET_NULL |
| reviewed_at | DateTimeField | nullable |
| **Edit trail** | | |
| edited_manually | BooleanField | True if any field was hand-corrected |
| edit_note | TextField | reason for manual edit |
| source_row_hash | CharField(64) | copied from raw record — dedup reference |
| created_at | DateTimeField | auto |

**Source reference uses `raw_record_id` + `raw_record_type`, not Django ContentTypes.**
With exactly three source types that are fixed at design time, Django's ContentType framework adds unnecessary overhead — a dependency, a separate DB table, and a runtime lookup on every FK resolution. A `PositiveIntegerField` + `CharField(30)` pair is simpler, faster, and sufficient. The type string (`"RawSAPRecord"`, `"RawUtilityRecord"`, `"RawTravelRecord"`) maps to a concrete model in application code via a lookup dict. See DECISIONS.md.

**`reviewed_by` uses `on_delete=SET_NULL`, not CASCADE.**
If an analyst's user account is deleted, the records they approved must not be deleted with it. The approval event is real and may already be in a regulatory filing. `SET_NULL` preserves the emission record and nulls only the FK. The analyst's username is captured at read time via the serializer.

**`is_locked` is the audit boundary, `status` is the display label.**
`status='approved'` tells the analyst UI what to show. `is_locked=True` is what the backend checks before allowing any modification. The approve endpoint sets both simultaneously. All downstream code checks `is_locked` first — a locked record cannot be modified regardless of what `status` holds.

**`reporting_month` is a `CharField(7)`, not a `DateField`.**
A billing period from 18 January to 19 February belongs to February by majority month. Storing this as `2026-02-01` (DateField with forced `day=1`) implies a precision that does not exist — the emission did not occur on February 1st. `reporting_month` is a period label, not a timestamp. `CharField` stores exactly what it represents.

---

## Scope Classification

| Source | Scope | GHG Protocol Category | Rationale |
|--------|-------|-----------------------|-----------|
| SAP — all fuel types (FUEL01–FUEL04) | 1 | Scope 1 — Stationary Combustion | Direct combustion, company-owned or operated assets |
| Utility — electricity | 2 | Scope 2 — Purchased Electricity | Purchased indirect energy — company does not own generation |
| Travel — flights | 3 | Scope 3 — Cat. 6 Business Travel | Business travel, third-party carrier |
| Travel — hotels | 3 | Scope 3 — Cat. 6 Business Travel | Business travel, third-party property |
| Travel — ground, company_vehicle | 1 | Scope 1 — Mobile Combustion | Direct combustion, company asset (mobile combustion) |
| Travel — ground, third_party | 3 | Scope 3 — Cat. 6 Business Travel | Purchased transport service |

Ground transport scope is determined by `provider_type`, not `expense_type`. A taxi and a company car are both "ground transport" by expense type, but they sit in different scopes — one is a direct emission from a company asset, the other is a purchased service from a third party.

---

## Source-of-Truth Tracking

The assignment requires tracking which source produced each row, when it was ingested, and whether it was subsequently edited. These are structural properties of the schema, not application features.

**Which source produced this row?**
`source_type` (sap / utility / travel) identifies the source category. `raw_record_id` + `raw_record_type` form a resolvable pointer to the exact raw record in the exact raw table that produced this emission entry. Following that pointer gives the original, unmodified source data exactly as it arrived — including the `raw_payload` JSONField on the SAP batch, which stores the entire OData response verbatim.

**When was it ingested?**
`created_at` on the raw record is the ingestion timestamp — set automatically on insert, never modified. For SAP, the batch record also carries `created_at` covering the full trigger call. For utility and travel, the batch record stores the original upload filename and timestamp.

**Was it manually edited after ingestion?**
The database schema includes placeholders `edited_manually` (BooleanField) and `edit_note` (TextField) to support future manual correction workflows. However, in the current implementation, post-normalization manual edits are **not supported**; there is no API endpoint or UI interface to hand-correct a record after normalization. Thus, `edited_manually` remains `False` and `edit_note` remains empty. (Additionally, the `updated_at` field is omitted from the model as records are immutable upon ingestion and only transition between review statuses).

---

## Audit Trail

The audit trail is not a feature — it is a structural property of the schema.

For any row in `NormalizedEmissionRecord`, an auditor can answer:

- **Where did this come from?** → `source_type` + `raw_record_id` + `raw_record_type` → joins directly to the exact raw record (`RawSAPRecord`, `RawUtilityRecord`, or `RawTravelRecord`).
- **What did the source actually send?** → The raw fields of the corresponding raw record, the original uploaded CSV name (`source_file_name`) stored on the Utility/Travel ingestion batches, or the verbatim JSON response (`raw_payload`) stored on the SAP batch.
- **When was it ingested, and in what batch context?** → The batch creation timestamp (`created_at`) and the row insertion timestamp (`raw_record.created_at`), which record the exact operational execution run.
- **What emission factor was applied, and from where?** → `emission_factor` + `emission_factor_source` (e.g., state-specific grid factors from CEA 2023 for utilities, Defra factors for travel routes, or location-based factors for SAP plants).
- **Who reviewed it?** → `reviewed_by` (User FK) captures which user (e.g. analyst/reviewer) approved or rejected the entry.
- **When was it locked?** → `reviewed_at` timestamp and `is_locked=True` establish the immutable audit boundaries.
- **Was it ever manually corrected after ingestion?** → Post-normalization manual overrides are **not supported** (no API endpoint or UI exists to edit records). The fields `edited_manually` (always `False`) and `edit_note` (always empty) exist in the database model solely as schema placeholders to support future manual correction workflows.

This chain — source → batch/raw → normalized → reviewed → locked — is complete, balanced across all three ingestion streams, and entirely unbroken.
