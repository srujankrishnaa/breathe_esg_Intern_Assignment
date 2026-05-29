# DECISIONS

## Breathe ESG — Emissions Ingestion Platform
Every ambiguity resolved, what was chosen, and why.

---

## Source Format Decisions

### SAP — OData V2, not IDoc or BAPI

**What was researched:** SAP exposes procurement and fuel data through several mechanisms. IDocs are the traditional EDI batch format — flat files with fixed-width segments, used heavily in legacy integrations. BAPIs are function modules callable via RFC. OData V2 is the modern REST-like interface exposed by SAP Gateway, used by Fiori apps and by most new integrations since SAP introduced Gateway around 2013.

**Decision:** OData V2.

**Why:** OData is the format a new enterprise client's IT team is most likely to expose without custom development. It returns JSON. The URL structure is predictable (`/sap/opu/odata/sap/MM_PUR_POSIT_SRV/PurchaseOrderSet`). The date format (`/Date(milliseconds)/`) is well-documented, even if unpleasant. IDoc requires an ALE/EDI configuration that most clients have not set up for data extraction purposes. BAPI requires an RFC-capable connector that adds infrastructure dependencies outside the prototype scope.

**What I would ask the PM:** Which SAP modules does the client have active? Is SAP Gateway configured? Is there a technical contact on the client side who can share the exact OData endpoint and entity set name they use for procurement?

**What breaks:** Clients on older SAP versions without Gateway, or clients using SAP S/4HANA with a different OData namespace, cannot be onboarded without a custom adapter. Documented in TRADEOFFS.md.

---

### Utility — Portal CSV Export, Not PDF or Direct API

**What was researched:** Indian state electricity boards (DISCOMs) typically provide bills as PDFs. Some also offer portal logins where facilities teams can download CSV exports of consumption history. A few utilities (BESCOM, MSEDCL, TGSPDCL, APSPDCL) have nascent data APIs, but access requires utility-specific registration, varies by circle, and is not standardised.

**Decision:** Portal CSV export.

**Why:** PDF parsing requires OCR or layout-aware PDF parsing (pdfplumber, camelot). Bill layouts differ across utilities and change without notice. CSV from a portal is already structured and is the format a facilities manager actually uses when asked to "pull the electricity data." Direct utility APIs are not consistently available across the three utilities represented in the mock data. Additionally, adopting a standardized CSV export format makes it significantly easier to mimic and programmatically generate high-fidelity test files by understanding how the actual real-world data logs look in practice.

The 19-column cross-utility schema in `RawUtilityRecord` was designed around actual BESCOM, MSEDCL, and TGSPDCL portal exports. Each utility uses a different identifier field for the account (rr_number, consumer_number, usc_no). Each includes a raw tariff label that must be normalised. All include meter readings and derived consumption.

**What I would ask the PM:**
- Will the facilities managers upload direct CSV portal exports, or will they be manually transcribing from PDF bills?
- Do the portal exports already apply the meter constant to the reported consumed units, or do I need to multiply the reading difference by the constant ourselves? Are the units always explicitly kWh?
- What are the exact customer tariff structures I need to support, and how should they map to HT/LT or commercial reporting categories?
- Since billing cycles do not align with calendar months (e.g. Dec 18 to Jan 17), does the client approve of using my majority-of-days rule for month attribution, or do they require splitting emissions proportionally across both calendar months?

**What breaks:** If a utility changes its CSV column layout, the parser breaks silently — it would produce zero-value records rather than errors unless column validation is added. Documented in TRADEOFFS.md.

---

### Travel — CSV Export, Not Concur/Navan OAuth

**What was researched:** Concur's Travel and Expense API offers OAuth 2.0 access to booking data, itinerary details, and expense reports. Navan (formerly TripActions) offers a similar REST API. Both require OAuth client credentials registered with the travel management company, which requires the client's IT procurement team and in some cases a platform subscription.

**Decision:** CSV export from the travel platform.

**Why:** OAuth requires per-client credential provisioning, refresh token management, and handling pagination across potentially thousands of booking records. For a prototype evaluating the ingestion pipeline and data model, this is disproportionate infrastructure. The CSV schema was designed to match the actual column structure of a Concur trip export: external booking ID, segment ID, carrier codes, cabin class, IATA origin/destination, hotel check-in/check-out, ground transport mode. Additionally, by reviewing outputs from different travel platforms, I can easily analyze their underlying data structures and mimic them identically in a simplified CSV export format for testing and ingestion.

**What I would ask the PM:**
- What travel management platforms (e.g., Concur, Navan, or a local regional TMC) are currently in use, and does the client's travel administrator already have access to run manual exports?
- What ingestion frequency is acceptable for travel reports (e.g., a monthly batch upload of trip CSVs vs. real-time automated API pulls)?
- Since Scope 3 Category 6 (Business Travel) includes numerous subcategories (e.g., flight classes, short/medium/long-haul segments, specific hotel region emission factors, and third-party vehicle types), does the client require highly detailed category breakdown logs, or is the current high-level aggregation sufficient?

**What breaks:** Manual CSV upload is operationally fragile. A travel admin who forgets to export for two months, or exports the wrong date range, creates gaps in the emissions record. Documented in TRADEOFFS.md.

---

## Data Model Decisions

### Generic FK (raw_record_id + raw_record_type) Over Django ContentTypes

**Decision:** `raw_record_id` (PositiveIntegerField) + `raw_record_type` (CharField) on `NormalizedEmissionRecord`.

**Why:** Django's ContentType framework provides a generic FK mechanism backed by a `django_content_type` table. It is appropriate when the set of related models is open-ended or discovered at runtime. Here, there are exactly three source types and they will not change in this prototype. ContentType adds a dependency, a join to `django_content_type` on every FK resolution, and abstraction that obscures what is actually a simple three-way relationship. A CharField holding "RawSAPRecord" / "RawUtilityRecord" / "RawTravelRecord" is readable, queryable with a filter, and resolvable in application code with a dict.

---

### `reporting_month` as CharField(7) Not DateField

**Decision:** CharField(7) storing "YYYY-MM".

**Why:** A utility billing period from 18 January to 19 February belongs to February by majority month. Storing the reporting period as `2026-02-01` (DateField with forced day=1) implies a level of precision that doesn't exist — the emission did not occur on February 1st. "YYYY-MM" is a period label. It is filtered as a string, displayed as a string, and grouped as a string. DateField would introduce a silent fiction.

---

### `reviewed_by` Uses `on_delete=SET_NULL` Not CASCADE

**Decision:** SET_NULL.

**Why:** Deleting a user account is an HR or access management action. It must not propagate to emission records that the user approved. Those records may already be in an audit submission or regulatory filing. SET_NULL preserves the record, nulls the FK, and the record remains fully intact. The username at review time can be recovered from `reviewed_by_username` on the serializer if the FK has been nulled.

---

### `is_locked` Is the Hard Boundary, Not `status`

**Decision:** Approve sets both `status='approved'` AND `is_locked=True`. All modification guards check `is_locked` first.

**Why:** `status` is a business-layer label that communicates state to the analyst UI. `is_locked` is the audit-layer enforcement mechanism. If a future code path inadvertently changes `status` without going through the approve endpoint, `is_locked=True` still prevents modification. The two fields serve different layers and checking the stronger constraint first (is_locked) before the weaker one (status) is the correct guard order. The handoff documents this explicitly: "is_locked is the hard boundary — not status."

---

### Duplicate Detection Via Source Row Hash on Raw Table

**Decision:** SHA256 hash of identifying fields, stored on the raw record, checked before raw record creation.

**Why:** The check must run before creating the raw record — otherwise a duplicate raw record exists even if normalization is skipped. If the check ran against the normalized table, a row with a normalization failure (no normalized record created) would be reprocessed on every subsequent ingestion, potentially accumulating duplicate raw records. Hashing on the raw table and checking before insert is the correct sequence.

Hash inputs per source:
- SAP: plant_code + material_group + quantity + document_date + purchase_order + purchase_order_item
- Utility: utility + meter_id + billing_period_from + billing_period_to
- Travel: external_booking_id + segment_id + expense_type

---

### Token Stored in Memory, Not localStorage

**Decision:** In-memory JavaScript variable, not `localStorage`.

**Why:** localStorage persists across sessions and is accessible to any JavaScript on the page. An XSS vulnerability — even in a third-party script — can exfiltrate the token. In-memory storage means a page refresh requires re-login, which is an acceptable UX tradeoff for a prototype. In production, the correct solution is an httpOnly cookie set by the backend on login, which JavaScript cannot read at all. This decision is documented as a comment in api.js.

---

### SAP Trigger Generates Fresh Payload by Default

**Decision:** Default POST to `/api/ingest/sap/trigger/` generates a fresh OData payload using `generate_sap_payload()`. The `?file=` parameter loads a specific test simulation payload.

**Why:** A real SAP OData integration would make an outbound HTTP call to the SAP Gateway URL on every trigger. The generator mimics this behavior — each call produces different PO numbers, so a second trigger creates new rows rather than duplicates. The test simulation payloads are retained for error scenario testing (unknown plant code, high quantity flags) where deterministic data is required. Swapping the generator for a real HTTP call in production requires changing one function — the downstream ingestion pipeline is identical.

---

### Fallback Grid Factor for Unmapped Utilities

**Decision:** Default fallback factor is set to `0.82 kg CO₂e/kWh` (corresponding to Karnataka's grid factor/BESCOM).

**Why:** The primary testing tenant, Acme Industries, has its main operations based in Karnataka/BESCOM. Using `0.82` represents a conservative estimation approach (higher baseline emissions value) that matches the primary facility's region when specific DISCOM mapping is unavailable. In a production deployment, the fallback factor would default to the national grid average (CEA 2022-23 publishes `0.716 kg CO₂e/kWh`) or require a dynamic DISCOM/state lookup service to avoid regional bias.

---

### Simplified Tariff Classification (HT vs LT)

**Decision:** The `tariff` field stores a normalized classification (`HT` or `LT`), rather than preserving full utility-specific tariff codes (like LT-II, HT-1).

**Why:** Indian utilities feature highly fragmented and frequently changing tariff schedules. Coercing these into the core voltage classifications (High Tension and Low Tension) simplifies the database schema and routing logic, while the human-readable utility-specific label is preserved in the `raw_tariff_label` field to maintain full audit trail fidelity.

---

### Non-CT Meter Constant Default

**Decision:** `meter_constant` defaults to `1.0000` (or `null`) for direct-read connections.

**Why:** Only Current Transformer (CT) metered industrial connections require a multiplier ratio (such as `40` for my Mumbai factory). Defaulting the constant to `1.0000` allows the consumption parser to run the same mathematical formula (`units_consumed * meter_constant`) across all connections without adding conditional branches.

---

### Omission of Billing Amount

**Decision:** Financial data (`amount_billed` or `bill_amount`) is explicitly excluded from the database schema.

**Why:** The prototype's scope is strictly confined to carbon emissions inventory tracking, not financial auditing or utility bill reconciliation. Any billing dispute workflows are out of scope; thus, financial metrics are omitted to avoid database overhead and security complexity.

---

## Infrastructure & Deployment Decisions

### Backend Hosting & Database

**Decision:** Deployed the backend on Render as a Web Service with a managed PostgreSQL database, and configured an UptimeBot to keep the server alive.

**Why:** A primary ambiguity for prototyping is how to deploy a free-tier service without sacrificing UX due to "cold starts" or losing data between sessions (which happens with ephemeral file-based DBs like SQLite on ephemeral file systems). I chose Render because it natively supports Docker and PostgreSQL. To resolve the free-tier sleep issue (where free instances spin down after 15 minutes of inactivity, causing 30-60 second delays on the next request), I implemented an external pinging mechanism (like UptimeBot or a Cron job) to periodically hit the backend's `/api/health` endpoint. This ensures the prototype remains fast and responsive for reviewers without requiring an immediate upgrade to a paid tier.

---

## Questions Not Resolved (What I Would Ask the PM)

1. What is the client's fiscal year — April–March (India standard) or calendar year? This affects which reporting_month a cross-boundary billing period belongs to.

2. Are there multiple meters per plant? The current model assumes one utility account per ingestion row. Multiple meters at one plant require aggregation before or after normalization.

3. What emission factor vintage does the client's auditor accept? CEA publishes annual grid emission factors. If the client's auditor requires a specific year, the hardcoded CEA 2022-23 factor may need updating.

4. Is cancelled travel excluded from emissions reporting, or included as a policy signal? The travel normalizer currently flags cancelled bookings as suspicious. Some clients want them excluded entirely; others want them visible.

5. Does the client use a single SAP system or multiple? Plant codes 1010, 2030, 3050 are seeded as known. Procurement from a plant not in the lookup table currently creates a suspicious record. A second SAP instance with different plant codes would require re-seeding PlantLookup.

6. **Failed row persistence:** Should rows that fail validation during ingestion be stored in the database for permanent audit trail, or is session-only visibility sufficient? Current prototype surfaces failed rows in the UI during the same session but does not persist them. A production system inspired by Sweep ESG's evidence layer would likely store them — every row that entered the system, successful or not, should be traceable. This requires a `FailedIngestionRow` model and a separate audit view.

7. **Bulk approve scope:** When an analyst clicks "Approve All Pending," should suspicious records be included or excluded? Current implementation excludes suspicious records from bulk approve — they require individual review. Sweep ESG's governance philosophy suggests suspicious records should always be individually reviewed, but some clients may want a "bulk approve with override" option for efficiency. The current behavior is the conservative default.

8. **Suspicious record override workflow:** When an analyst approves a suspicious record, should they be required to provide a justification note? Current prototype allows approval without a note. A production system would likely require a mandatory justification note when overriding a suspicious flag to create a reviewable evidence trail for auditors.

9. **Evidence attachment:** Should the review dashboard support attaching evidence (PDFs, screenshots, supplier confirmations) to approved records? Sweep ESG's platform emphasizes evidence management alongside approvals. The current prototype records _who_ approved and _when_, but not the _supporting document_ that justified the approval. Adding an `EvidenceAttachment` model with file upload is a natural production extension.

10. **Record edit capability:** Should analysts be able to correct data before approving (e.g., fix a typo in quantity)? The current implementation strictly enforces **no manual edits** after normalization to maintain an unbroken audit trail—if data is wrong, it must be fixed at the source and re-ingested. While the database schema includes `edited_manually` and `edit_note` fields as placeholders, I deliberately left them inactive. Enabling in-app edits would trade data integrity for analyst flexibility and severely complicate the auditor's ability to trust the data.
