# TRADEOFFS

## Breathe ESG — Emissions Ingestion Platform
Three things deliberately not built, and exactly what breaks because of each cut.

---

## 1. Single SAP Format — OData V2 Only

**What was built:** The SAP ingestion pipeline handles one format: OData V2 JSON with the PurchaseOrderSet entity structure. By exposing a direct HTTP endpoint (`/api/ingest/sap/trigger/`), it supports REST-style API calling, which makes simulating and mimicking the SAP integration flow extremely straightforward. The mock generator produces this format, the test simulation payloads are in this format, and the normalizer expects this structure.

**What was not built:** IDoc flat file parsing, BAPI function module integration, SAP S/4HANA OData V4 support, German column header variants, RFC-based connectors.

**What breaks in production:**

Clients running SAP ECC 6.0 without SAP Gateway configured cannot use this ingestion path at all. Gateway is a separate component that must be installed and configured; not all SAP instances have it. An SAP Basis admin can confirm in minutes whether Gateway is available — but if it is not, there is no fallback in this implementation.

Clients using SAP S/4HANA Cloud (SAP's SaaS offering) use OData V4, which has a different JSON envelope structure. The `/Date(ms)/` date format used here is OData V2-specific. OData V4 uses ISO 8601 dates. The current parser would silently produce null dates on an S/4HANA response.

Clients in German-language SAP configurations may receive column headers like `Bestellmenge` (order quantity), `Buchungsdatum` (document date). The current parser reads English field names only.

**The cost of the cut:** Any client with non-OData-V2 SAP requires a custom adapter before they can onboard. This is engineering work per client, not configuration work. At three or more clients with different SAP configurations, a format abstraction layer becomes necessary.

---

## 2. Static Emission Factors — DEFRA 2023 and CEA 2022-23, Hardcoded

**What was built:** All emission factors are hardcoded constants in `ingestion/normalizers/constants.py`. SAP fuel factors come from DEFRA 2023 (UK government conversion factors, widely used as an international reference). Electricity factors use state-wise grid factors from the CEA 2022-23 database for India (e.g. Karnataka: 0.820, Maharashtra: 0.750, Telangana: 0.910 kg CO₂e/kWh), falling back to a default of 0.820 kg CO₂e/kWh. Flight factors come from DEFRA 2023 aviation section, with radiative forcing already baked into the factor values.

**What was not built:** An emission factor management interface, a versioned factor table, an annual update pipeline, or a mechanism to reprocess historical records when factors change.

**What breaks in production:**

Emission factors go stale. CEA publishes updated national and regional grid factors annually, typically in Q3 of the following year. DEFRA publishes updated conversion factors each June. A prototype deployed in May 2026 using CEA 2022-23 factors is already using three-year-old electricity emission data. For regulatory filings, the accepted factor vintage varies by jurisdiction — some require the factor current at the time of emission, others require the factor current at the time of reporting.

There is no way to reprocess historical records when factors update. The `emission_factor` and `emission_factor_source` fields are written once at normalization time. If CEA releases a corrected factor, every historical electricity record needs to be re-normalized from its raw record. The infrastructure for that reprocessing does not exist.

The static factors cannot be edited dynamically. If a DISCOM is not in the hardcoded state-wise lookup table, it falls back to a default state-level factor (Karnataka/BESCOM: 0.82) rather than resolving to its actual regional grid factor or the national average. A real production system would require a dynamic DISCOM/state lookup service.

**The cost of the cut:** Annual factor updates require a code change and redeployment. Any client undergoing a rigorous third-party audit will need factor versioning and the ability to demonstrate which factor was applied to which record at which point in time.

---

## 3. No RBAC — Single User Role

**What was built:** One user type. The analyst user can ingest data, view all records, approve records, and reject records. There is no separation between who ingests data and who reviews it. Rejection sets status='rejected' and preserves is_locked=False, keeping the record available for re-review. The raw record is always retained as the correction foundation.

**What was not built:** Role-based access control, a separate reviewer role, an auditor read-only role, approval workflows requiring a second reviewer, any restriction preventing a user from approving their own ingestion, a rejection_reason field, data owner notifications, or a resubmission workflow connecting the analyst back to whoever provided the original data.

**What breaks in production:**
The absence of separation of duties is a known audit control gap. Most ESG assurance frameworks (GHG Protocol, ISO 14064, CDP) and financial audit standards require that the person who inputs data cannot be the same person who signs off on it. An analyst who runs the SAP ingestion and then approves those same records is performing both roles in a single-actor workflow. For a regulated submission, this would be flagged by an external auditor.

An auditor read-only role does not exist. If an external auditor needs to inspect the dashboard, they would need to use the analyst credentials. This means they have approve and reject capabilities during their review, which is unsafe.
There is no workflow for escalation or second approval. Some clients require dual approval for records above a CO₂e threshold, or for any record marked suspicious. None of that logic exists.

Rejection is also a silent operation toward the data owner. When an analyst rejects a record, the plant manager, facilities team, or travel desk who submitted the original data has no way of knowing it was rejected, why it was rejected, or what correction is needed. The raw record is preserved precisely so that corrected data can be compared against the original submission — but without a data owner persona, a rejection_reason field, and a resubmission path, that preservation has no mechanism to act on it. The correction loop exists in the data model but not in the workflow.

**The cost of the cut:** Adding RBAC requires extending the UserProfile model with a role field, adding role checks to every view, building a separate auditor-facing read-only dashboard, and implementing whatever approval workflow the client's governance process requires. Closing the rejection loop additionally requires a rejection_reason field on NormalizedEmissionRecord, a notification layer to alert data owners, and a resubmission path that ties corrected source data back to the originally rejected record. Together this is significant scope — needs more time and database modelling so that each role will be defined architecturally — and requires a conversation with the client about their assurance requirements and organizational structure before the data model can be finalized.
