# SOURCES

## Breathe ESG — Emissions Ingestion Platform
For each source: what was researched, what was learned, what the mock data captures, and what would break in real deployment.

---

## Source 1 — SAP Fuel and Procurement Data

### What Was Researched

SAP procurement data lives in the Materials Management (MM) module. Purchase orders for fuel and consumables sit in the ME2M / ME2L transaction family. The modern way to expose this over an API is SAP OData V2 via SAP Gateway, specifically the `MM_PUR_POSIT_SRV` service which exposes the `PurchaseOrderSet` entity.

Key findings from researching real SAP OData responses:

**Date format:** SAP OData V2 encodes dates as `/Date(milliseconds_since_epoch)/` — for example, `/Date(1704067200000)/` for 2024-01-01. This is a quirk of OData V2's JSON serialization. OData V4 (S/4HANA) uses ISO 8601 instead.

**Plant codes:** Plant codes in SAP are 4-character alphanumeric identifiers (1010, 2030, AB01) that are meaningful only within a client's specific SAP configuration. They have no intrinsic meaning. A lookup table is mandatory to resolve a plant code to a location.

**Material groups:** SAP uses material group codes to classify what was purchased. For fuel, a typical configuration uses codes like FUEL01 (diesel), FUEL02 (petrol), FUEL03 (LPG), FUEL04 (furnace oil), though naming conventions vary by client. The material group — not the material description — is what the normalizer uses to look up the correct emission factor.

**Units:** SAP stores quantity units as SAP internal codes. Volume fuels (diesel, petrol) use L (litres) or GAL (gallons). Weight-sold fuels (LPG) use KG or TO (metric tonnes). LPG is always weight-based in SAP because LPG is sold by weight in India — suppliers invoice in kilograms, not litres. Giving LPG a volume unit would require a density conversion that varies with temperature and pressure and is not available in procurement data.

**PO structure:** Each purchase order has a header (PurchaseOrder number, CompanyCode, Supplier) and one or more line items (PurchaseOrderItem, Material, MaterialGroup, OrderQuantity, Plant, DocumentDate).

### What the Mock Data Captures (and Why)

**Why this format:** As documented in `DECISIONS.md`, I chose to mimic SAP OData V2 JSON responses rather than older legacy formats (IDocs, BAPIs) because OData is the modern standard for SAP integration via SAP Gateway. Generating JSON payloads accurately represents what a middleware (like MuleSoft) or a direct API pull would encounter, allowing me to test exact schema mappings.

The sample data uses the OData V2 JSON envelope format (`{"d": {"results": [...]}}` or `{"value": [...]}`). It captures realistic variations of purchase order line items across my regional plants, including:

- **Standard Procurement:** A mix of volume-based fuels (diesel in Litres) and weight-based fuels (LPG in Kilograms/Tonnes), utilizing correct SAP date formats and material group codes.
- **Outlier Scenarios:** Orders with unusually high quantities (e.g., >100,000 units) that mimic data entry errors (like entering KG instead of TO) to test suspicious flagging logic.
- **Geographic Misalignments:** POs tied to unknown plant codes, proving that the system can catch records where regional emission factors cannot be resolved.

### What Would Break in Real Deployment

1. **SAP Gateway not configured.** If the client's SAP instance does not have Gateway installed, there is no OData endpoint to call. Requires SAP Basis work to enable.

2. **Authentication.** Real SAP OData requires HTTP Basic Auth or OAuth 2.0 via SAP Identity Provider. The prototype has no authentication mechanism on the SAP call — it either generates locally or reads a file.

3. **Pagination.** SAP OData returns results in pages (`$top` and `$skip` parameters). A client with 50,000 purchase orders per month would require pagination handling. The current implementation processes whatever is in the `value` array of a single response.

4. **Material group taxonomy.** The FUEL01–FUEL04 codes are invented for this prototype. A real client's SAP may use completely different codes (e.g. "RMENERG", "TREIBST", or numeric codes) requiring a client-specific mapping table.

5. **Delta extraction.** The prototype ingests whatever the trigger returns. A production integration would need delta extraction — only new or changed records since the last pull — to avoid reprocessing the entire procurement history every time.

---

## Source 2 — Utility Electricity Data

### What Was Researched

India has 28 state DISCOMs (Distribution Companies) plus several privatised utilities in metros. The major ones researched and utilized in the mock data for this prototype include:

- **MSEDCL** (Maharashtra State Electricity Distribution Co. Ltd) — covers Mumbai Factory (plant 1010), Maharashtra
- **BRPL / BYPL** (BSES) or **TPDDL** — covers Delhi Warehouse (plant 2030), Delhi
- **TANGEDCO** (Tamil Nadu Generation and Distribution Corporation) — covers Chennai Plant (plant 3050), Tamil Nadu
- **TGSPDCL** (Telangana State Southern Power Distribution Company Limited) — covers Telangana region
- **BESCOM** (Bangalore Electricity Supply Company Limited) — covers Karnataka region

Key findings from researching actual Indian utility bill exports:

**Meter identifier fragmentation:** Every DISCOM uses a different term for what is functionally the same thing — the account number. BESCOM uses `rr_number` (Revenue Register number). MSEDCL uses `consumer_number`. TGSPDCL uses `usc_no` (Universal Supply Code). Some utilities provide an `account_id` as well. A cross-utility schema needs all four columns, nullable, with the normalizer resolving whichever is populated.

**Billing period mismatch:** Utility billing cycles are not calendar months. MSEDCL bills HT (High Tension) consumers monthly but LT (Low Tension) consumers bimonthly. BESCOM bills commercial consumers monthly. A billing period might run from the 18th of one month to the 17th of the next. The `reporting_month` is assigned by majority month — if more than 15 days of a billing cycle fall in February, the record is attributed to February.

**Meter readings:** Bills include previous reading, present reading, and derived units consumed. For CT (Current Transformer) metered connections (large industrial loads), a `meter_constant` (CT ratio) multiplies the reading difference to get actual consumption. Ignoring the meter constant for CT-metered industrial plants would produce consumption figures that are 50–200x too low.

**Meter status:** A `meter_status` field indicates whether the meter was working during the period. Values like "Defective", "Door Locked", "Average" indicate the bill is based on estimated consumption, not actual readings. The normalizer uses `average_units` for these rows when available.

**Tariff codes:** Each DISCOM has its own tariff schedule. HT-I is High Tension Industrial in most DISCOMs; LT-II is Low Tension Commercial. The raw bill prints the tariff label as a human-readable string. The normalizer normalises this to a canonical code (HT, LT) for routing purposes.

**CEA emission factor:** The Central Electricity Authority publishes grid emission factors. For 2022-23 (Version 18.0, published in 2023), the national average is 0.716 kg CO₂e per kWh. To improve carbon accounting precision, the prototype maps specific utilities (DISCOMs) to their corresponding state-level grid factors from the CEA 2022-23 database (Karnataka/BESCOM: 0.82, Maharashtra/MSEDCL: 0.75, Telangana/TGSPDCL: 0.91 kg CO₂e/kWh), falling back to 0.82 kg CO₂e/kWh for unmapped utilities.

### What the Mock Data Captures (and Why)

**Why this format:** As outlined in `DECISIONS.md`, I chose CSV portal exports rather than PDF bills or direct APIs. PDF parsing requires complex layout-aware OCR which introduces noise and brittleness. Direct utility APIs are practically non-existent or heavily gated for the Indian DISCOMs researched. CSV exports are the real-world format facilities managers use to download bulk data, and they are structured and easy to reliably mimic for the prototype.

To simulate a realistic, region-specific ESG inventory audit, the mock datasets tie your registered facility regions (Mumbai/Maharashtra, Delhi, Chennai/Tamil Nadu) and additional test regions (Karnataka, Telangana) directly to their local electricity grids (MSEDCL, TANGEDCO, BESCOM, TGSPDCL) and business travel routes (e.g., BOM to DEL flights). This regional alignment proves that the platform can ingest disparate data points and correctly map them back to localized emission factors.

The sample data is structured as flat CSV exports utilizing a 19-column schema that represents the union of fields across major Indian utility portals. It captures:

- **Standard Billing:** Monthly and bimonthly bills spanning multiple geographic tariffs (High Tension vs Low Tension), incorporating CT meter constants for large industrial loads.
- **Billing Period Misalignments:** Bills spanning across month boundaries (e.g., Dec 18 - Jan 17) to demonstrate the majority-month attribution rule.
- **Multi-Meter & Multi-Utility Complexity:** Multiple meters aggregated at a single plant, and singular files containing rows from entirely different DISCOMs to prove correct regional emission factor routing.
- **Data Quality Issues:** Defective meter statuses and statistically unlikely consumption spikes that would trigger review from an analyst in the real world.

### What Would Break in Real Deployment

1. **CSV column layout changes.** If MSEDCL adds a column or renames a column in their portal export, the parser produces null values for that field without error. Column validation would need to check for required columns before processing.

2. **PDF bills.** Many plant managers receive PDF bills, not portal CSV exports. The prototype explicitly does not handle PDFs. A PDF parsing layer (pdfplumber, tabula-py) would be needed for clients who cannot get portal access.

3. **Missing portal access.** Some plant facilities teams do not have portal login credentials. They receive paper bills and manually key data. The prototype has no manual entry UI.

4. **Demand charges and power factor penalties.** Indian HT bills include maximum demand (MD) charges, power factor adjustment, and various surcharges that are not consumption-based. These do not contribute to Scope 2 emissions and are ignored in the normalizer, but they are present in the bill data and a facilities team might upload a full bill CSV expecting them to be parsed.

5. **Multi-tariff billing periods.** Some bills cover a period during which a tariff change occurred, resulting in two rate blocks in one billing period. The 19-column schema has one set of consumption fields per row — it cannot represent a single bill with two tariff blocks.

---

## Source 3 — Corporate Travel Data

### What Was Researched

Concur Travel and Navan (formerly TripActions) are the dominant corporate travel management platforms in the Indian enterprise market. Both expose structured booking data. Concur's legacy export format is a flat CSV from the reporting module; Navan offers a similar CSV export. Both include:

**Flights:** Booking reference (PNR / record locator), carrier IATA code, flight number, origin and destination IATA airport codes, departure and arrival datetimes, cabin class, ticket number, booking status (confirmed / cancelled / modified), fare amount, trip type (one_way / return).

**Hotels:** Vendor name, city, country, check-in date, check-out date, nights, number of rooms, fare amount.

**Ground transport:** Transport mode (taxi, train, rental car, company car), distance in km (not always populated), fuel type (for company vehicles), trip date.

Key findings:

**Distances are not always given.** For flights, the IATA distance between origin and destination can be computed from a lookup table. For ground transport, distance is sometimes populated, sometimes absent. Without distance, ground transport emissions cannot be calculated.

**Cabin class matters substantially.** DEFRA 2023 flight emission factors are:
- Economy: 0.15510 kg CO₂e per passenger-km
- Premium economy: 0.23370 kg CO₂e per passenger-km  
- Business: 0.42840 kg CO₂e per passenger-km
- First: 0.59700 kg CO₂e per passenger-km

A business class flight emits approximately 2.8x more per passenger than economy. Cabin class is always available in the booking data.

**Radiative forcing is already in DEFRA factors.** DEFRA 2023 aviation factors include a 1.9x radiative forcing multiplier — accounting for the non-CO₂ warming effects of aviation (contrails, NOx, water vapour at altitude). This is baked into the factor values. Applying an additional RF multiplier would double-count it. The constants file includes `RADIATIVE_FORCING_INCLUDED = True` to document this explicitly.

**Cancelled bookings.** A cancelled booking still has a fare charge in many cases (non-refundable fares) but zero actual travel. The normalizer flags cancelled bookings as suspicious — they should not contribute to the emissions record but the analyst should explicitly confirm this.

**Ground transport scope depends on asset ownership.** A taxi and a company car both appear as "ground transport" in the booking data. Their Scope classification is different: company car = Scope 1 (direct combustion, company asset); taxi / Uber / train = Scope 3 (purchased service, third-party asset). The `provider_type` field encodes this distinction: `company_vehicle` maps to Scope 1, everything else maps to Scope 3.

**IATA distance lookup.** The prototype uses a hardcoded table of IATA airport pairs for major Indian routes (BOM-DEL, BOM-BLR, DEL-BLR, etc.) plus selected international routes. Unknown route pairs (both codes present but not in the lookup) trigger a suspicious flag — the emission cannot be calculated without the distance.

### What the Mock Data Captures (and Why)

**Why this format:** As discussed in `DECISIONS.md`, I opted for CSV exports mimicking Concur/Navan rather than direct API integrations (which are often locked behind enterprise OAuth scopes). CSV reports are the standard way corporate travel managers extract historical booking data. Mimicking this format allowed me to easily generate large varieties of test data (different cabin classes, cancellations, scopes) that match the exact shape of real-world exports.

The sample data is structured as flat CSV exports utilizing a 35-column schema that covers flights, hotels, and ground transport within unified exports. It captures:

- **Flight Variations:** Domestic and international segments spanning multiple carriers, alongside mixed cabin classes (Economy vs Business) to demonstrate the stark difference in applied emission multipliers.
- **Hotel Stays:** Multi-night stays across different global regions (India, UK) to test country-specific hotel emission factors.
- **Ground Transport & Scope Mapping:** A mix of company-owned vehicles versus third-party transport to demonstrate how ownership correctly splits identical travel modes into Scope 1 versus Scope 3.
- **Booking Anomalies:** Cancelled bookings, unknown IATA routes, and missing distance metrics that represent common data quality gaps requiring analyst intervention.

### What Would Break in Real Deployment

1. **IATA distance lookup coverage.** The hardcoded lookup covers roughly 40 route pairs. A real client with a global travel programme would encounter hundreds of routes. Unknown routes produce suspicious records that the analyst must manually resolve. A production implementation would query an IATA distance API (e.g. aviationstack, OAG) or compute great-circle distance from airport coordinates.

2. **Concur export format changes.** Concur periodically updates its CSV report template. A column rename or reorder would break the parser. Column-name-based parsing (DictReader) is more resilient than positional parsing, but new columns introduced by Concur would require schema updates.

3. **Multi-currency fare amounts.** The prototype stores `fare_amount` but does not use it for emission calculation (emissions are distance-based, not cost-based). A cost-based emission approach (spend × spend-based emission factor) would require currency conversion, which adds FX rate dependencies.

4. **Hotel emission factors.** The DEFRA 2023 hotel factor used (0.165 kg CO₂e per room-night, UK average) is a very rough approximation. Hotel emissions vary significantly by property type, location, and energy source. Country-specific factors (India hotel average is substantially different from UK) are not used in the prototype.

5. **Missing segment IDs.** Some travel platforms do not populate a segment-level identifier in their CSV exports, only a booking-level ID. Without a segment ID, the dedup hash falls back to booking_id + expense_type, which cannot distinguish between an outbound and return flight on the same booking. A second import of the same file would skip both segments as duplicates — correct behaviour — but a file with a single booking containing two legs of the same type would conflate them.
