# TRADEOFFS

## Breathe ESG — Emissions Ingestion Platform
Three things deliberately not built, and exactly what breaks because of each cut.

---

## 1. Single SAP Format — OData V2 Only

**What was built:** The SAP ingestion pipeline handles one format: OData V2 JSON with the PurchaseOrderSet entity structure. The mock generator produces this format. The static test files are in this format. The normalizer expects this format.

**What was not built:** IDoc flat file parsing, BAPI function module integration, SAP S/4HANA OData V4 support, German column header variants, RFC-based connectors.

**What breaks in production:**

Clients running SAP ECC 6.0 without SAP Gateway configured cannot use this ingestion path at all. Gateway is a separate component that must be installed and configured; not all SAP instances have it. An SAP Basis admin can confirm in minutes whether Gateway is available — but if it is not, there is no fallback in this implementation.

Clients using SAP S/4HANA Cloud (SAP's SaaS offering) use OData V4, which has a different JSON envelope structure. The `/Date(ms)/` date format used here is OData V2-specific. OData V4 uses ISO 8601 dates. The current parser would silently produce null dates on an S/4HANA response.

Clients in German-language SAP configurations may receive column headers like `Bestellmenge` (order quantity), `Buchungsdatum` (document date). The current parser reads English field names only.

**The cost of the cut:** Any client with non-OData-V2 SAP requires a custom adapter before they can onboard. This is engineering work per client, not configuration work. At three or more clients with different SAP configurations, a format abstraction layer becomes necessary.

---

## 2. Static Emission Factors — DEFRA 2023 and CEA 2022-23, Hardcoded

**What was built:** All emission factors are hardcoded constants in `ingestion/normalizers/constants.py`. SAP fuel factors come from DEFRA 2023 (UK government conversion factors, widely used as an international reference). Electricity factors use the CEA 2022-23 national grid emission factor for India (0.716 kg CO₂e per kWh). Flight factors come from DEFRA 2023 aviation section, with radiative forcing already baked into the factor values.

**What was not built:** An emission factor management interface, a versioned factor table, an annual update pipeline, region-specific electricity factors, or a mechanism to reprocess historical records when factors change.

**What breaks in production:**

Emission factors go stale. CEA publishes updated national and regional grid factors annually, typically in Q3 of the following year. DEFRA publishes updated conversion factors each June. A prototype deployed in May 2026 using CEA 2022-23 factors is already using three-year-old electricity emission data. For regulatory filings, the accepted factor vintage varies by jurisdiction — some require the factor current at the time of emission, others require the factor current at the time of reporting.

There is no way to reprocess historical records when factors update. The `emission_factor` and `emission_factor_source` fields are written once at normalization time. If CEA releases a corrected factor, every historical electricity record needs to be re-normalized from its raw record. The infrastructure for that reprocessing does not exist.

Region-specific grid factors are more accurate than the national average. DEFRA 2023 has regional UK factors; CEA publishes state-level factors for India. Using the national average understates emissions for states with coal-heavy grids (Jharkhand, Chhattisgarh) and overstates them for states with high renewable penetration (Karnataka, Tamil Nadu, Rajasthan). The current model stores a single national factor for all utility records regardless of which state the meter is in.

**The cost of the cut:** Annual factor updates require a code change and redeployment. Any client undergoing a rigorous third-party audit will need factor versioning and the ability to demonstrate which factor was applied to which record at which point in time.

---

## 3. No RBAC — Single User Role

**What was built:** One user type. The analyst user can ingest data, view all records, approve records, and reject records. There is no separation between who ingests data and who reviews it.

**What was not built:** Role-based access control, a separate reviewer role, an auditor read-only role, approval workflows requiring a second reviewer, or any restriction preventing a user from approving their own ingestion.

**What breaks in production:**

The absence of separation of duties is a known audit control gap. Most ESG assurance frameworks (GHG Protocol, ISO 14064, CDP) and financial audit standards require that the person who inputs data cannot be the same person who signs off on it. An analyst who runs the SAP ingestion and then approves those same records is performing both roles in a single-actor workflow. For a regulated submission, this would be flagged by an external auditor.

An auditor read-only role does not exist. If an external auditor needs to inspect the dashboard, they would need to use the analyst credentials. This means they have approve and reject capabilities during their review, which is unsafe.

There is no workflow for escalation or second approval. Some clients require dual approval for records above a CO₂e threshold, or for any record marked suspicious. None of that logic exists.

**The cost of the cut:** Adding RBAC requires extending the UserProfile model with a role field, adding role checks to every view, building a separate auditor-facing read-only dashboard, and implementing whatever approval workflow the client's governance process requires. This is significant scope — likely two to three weeks of additional work — and requires a conversation with the client about their assurance requirements before the data model can be finalized.

---

## What Was Included Despite Being "Extra"

Multi-tenancy scaffolding is present (Tenant model, tenant FK on every object, tenant-scoped querysets) even though only one tenant is exercised. This was included because retrofitting tenant isolation onto an existing schema is significantly more disruptive than including it from the start. The scaffold is cheap to add; the absence of it is expensive to fix.
