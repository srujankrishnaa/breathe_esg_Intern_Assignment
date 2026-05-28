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

### What the Mock Data Captures

Three static JSON files and a dynamic generator, all in OData V2 format with the `{"d": {"results": [...]}}` or `{"value": [...]}` envelope:

**sap_normal.json** — 6 purchase order line items across plants 1010, 2030, 3050. Mix of FUEL01 (diesel, L), FUEL02 (petrol, L), FUEL03 (LPG, KG), FUEL04 (furnace oil, TO). DocumentDate in `/Date(ms)/` format. Quantities below 100,000 units. PO numbers in the SAP format: "45" prefix + 8 digits.

**sap_high_quantity.json** — Same structure, but two rows have OrderQuantity above 100,000 units. These trigger the `suspicious` status in the normalizer because quantities that large are unusual for a single purchase order line and may indicate a data entry error (e.g. KG entered instead of TO).

**sap_unknown_plant.json** — One row with a plant code (9999) not present in the PlantLookup seed data. This triggers a suspicious flag because without a plant lookup, the geographic region cannot be determined and the emission record is incomplete.

**sap_generator.py** — Produces a fresh OData payload on every call. Randomises PO numbers (format: "45" + 8 random digits) so that two successive calls to the SAP trigger endpoint produce different rows — no duplicates skipped. Enforces the LPG constraint: FUEL03 always gets KG or TO, never L or GAL. Quantities capped below 100,000.

### What Would Break in Real Deployment

1. **SAP Gateway not configured.** If the client's SAP instance does not have Gateway installed, there is no OData endpoint to call. Requires SAP Basis work to enable.

2. **Authentication.** Real SAP OData requires HTTP Basic Auth or OAuth 2.0 via SAP Identity Provider. The prototype has no authentication mechanism on the SAP call — it either generates locally or reads a file.

3. **Pagination.** SAP OData returns results in pages (`$top` and `$skip` parameters). A client with 50,000 purchase orders per month would require pagination handling. The current implementation processes whatever is in the `value` array of a single response.

4. **Material group taxonomy.** The FUEL01–FUEL04 codes are invented for this prototype. A real client's SAP may use completely different codes (e.g. "RMENERG", "TREIBST", or numeric codes) requiring a client-specific mapping table.

5. **Delta extraction.** The prototype ingests whatever the trigger returns. A production integration would need delta extraction — only new or changed records since the last pull — to avoid reprocessing the entire procurement history every time.

---

## Source 2 — Utility Electricity Data

### What Was Researched

India has 28 state DISCOMs (Distribution Companies) plus several privatised utilities in metros. The major ones relevant to the three plant locations in this prototype:

- **MSEDCL** (Maharashtra State Electricity Distribution Co. Ltd) — covers Mumbai Factory (plant 1010), Maharashtra
- **BRPL / BYPL** (BSES) or **TPDDL** — covers Delhi Warehouse (plant 2030), Delhi
- **TANGEDCO** (Tamil Nadu Generation and Distribution Corporation) — covers Chennai Plant (plant 3050), Tamil Nadu

Key findings from researching actual Indian utility bill exports:

**Meter identifier fragmentation:** Every DISCOM uses a different term for what is functionally the same thing — the account number. BESCOM uses `rr_number` (Revenue Register number). MSEDCL uses `consumer_number`. TGSPDCL uses `usc_no` (Universal Supply Code). Some utilities provide an `account_id` as well. A cross-utility schema needs all four columns, nullable, with the normalizer resolving whichever is populated.

**Billing period mismatch:** Utility billing cycles are not calendar months. MSEDCL bills HT (High Tension) consumers monthly but LT (Low Tension) consumers bimonthly. BESCOM bills commercial consumers monthly. A billing period might run from the 18th of one month to the 17th of the next. The `reporting_month` is assigned by majority month — if more than 15 days of a billing cycle fall in February, the record is attributed to February.

**Meter readings:** Bills include previous reading, present reading, and derived units consumed. For CT (Current Transformer) metered connections (large industrial loads), a `meter_constant` (CT ratio) multiplies the reading difference to get actual consumption. Ignoring the meter constant for CT-metered industrial plants would produce consumption figures that are 50–200x too low.

**Meter status:** A `meter_status` field indicates whether the meter was working during the period. Values like "Defective", "Door Locked", "Average" indicate the bill is based on estimated consumption, not actual readings. The normalizer uses `average_units` for these rows when available.

**Tariff codes:** Each DISCOM has its own tariff schedule. HT-I is High Tension Industrial in most DISCOMs; LT-II is Low Tension Commercial. The raw bill prints the tariff label as a human-readable string. The normalizer normalises this to a canonical code (HT, LT) for routing purposes.

**CEA emission factor:** The Central Electricity Authority publishes an annual CO₂ emission factor for the national grid. For 2022-23 (the most recent published as of this submission), the national average is **0.716 kg CO₂e per kWh**. CEA also publishes regional factors (Northern, Southern, Western, Eastern grid). The prototype uses the national factor; state-level factors would require mapping each DISCOM to a regional grid.

### What the Mock Data Captures

Five CSV files using a 19-column schema that covers the union of fields across BESCOM, MSEDCL, TGSPDCL, and TANGEDCO exports:

**utility_normal.csv** — Monthly bills from three meters, one per plant. Billing periods that cross month boundaries. Mix of HT (plant 1010, Mumbai) and LT (plants 2030, 3050) tariffs. CT-metered plant 1010 has a `meter_constant` of 40. Normal meter status.

**utility_suspicious.csv** — Rows with `units_consumed` above the 95th percentile threshold for an LT commercial connection (flagged as suspicious, possibly wrong reading units — MWh entered as kWh). One row with `meter_status = Defective` and no `average_units` — flagged because consumption cannot be estimated.

**utility_billing_misalignment.csv** — Billing periods that cross month boundaries (e.g. Dec 22 – Jan 21). Tests the majority-month attribution rule — 10 days in December, 21 days in January → January wins → `reporting_month = 2026-01`.

**utility_multi_meter.csv** — Multiple meters at a single plant (Mumbai Factory): HVAC meter, production meter, office meter. Different tariffs (HT and LT) and meter constants. Tests that per-meter consumption is normalised independently.

**utility_multi_utility.csv** — Rows from three different DISCOMs (BESCOM, MSEDCL, TGSPDCL) in one file. Tests that the normaliser correctly routes each row to the right state-level emission factor.

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

### What the Mock Data Captures

Five CSV files with the full 35-column travel schema covering all three expense types in a single file (expense_type column distinguishes them):

**travel_normal_flights.csv** — 8 flight segments. Mix of IndiGo, Air India, Vistara. Economy and business class. Domestic routes (BOM-DEL, BLR-HYD) and one international (BOM-LHR). Return trips represented as two separate segments (this is how Concur exports them). All routes in the IATA distance lookup.

**travel_hotels.csv** — 3 hotel stays. Marriott Mumbai, Taj Palace Delhi, Premier Inn London. Check-in/check-out dates, room counts, country code IN and GB. Tests country-specific hotel emission factor lookup.

**travel_ground_mix.csv** — 3 ground transport rows. One company vehicle (Scope 1, diesel, 120 km). One taxi via third-party (Scope 3, 45 km). One intercity train via third-party (Scope 3, 280 km). Tests the provider_type → Scope classification split.

**travel_flagged.csv** — Cancelled flight (booking_status = cancelled). Unknown IATA route (ZZZ-YYY). Hotel with zero nights (check_in = check_out — data entry error). Ground transport with provider_type = company_vehicle but no distance_km.

**travel_cabin_mix.csv** — Flights with mixed cabin classes (business and economy) across different carriers and routes. Tests that cabin class correctly affects the emission factor applied (business ≈ 2.8× economy).

### What Would Break in Real Deployment

1. **IATA distance lookup coverage.** The hardcoded lookup covers roughly 40 route pairs. A real client with a global travel programme would encounter hundreds of routes. Unknown routes produce suspicious records that the analyst must manually resolve. A production implementation would query an IATA distance API (e.g. aviationstack, OAG) or compute great-circle distance from airport coordinates.

2. **Concur export format changes.** Concur periodically updates its CSV report template. A column rename or reorder would break the parser. Column-name-based parsing (DictReader) is more resilient than positional parsing, but new columns introduced by Concur would require schema updates.

3. **Multi-currency fare amounts.** The prototype stores `fare_amount` but does not use it for emission calculation (emissions are distance-based, not cost-based). A cost-based emission approach (spend × spend-based emission factor) would require currency conversion, which adds FX rate dependencies.

4. **Hotel emission factors.** The DEFRA 2023 hotel factor used (0.165 kg CO₂e per room-night, UK average) is a very rough approximation. Hotel emissions vary significantly by property type, location, and energy source. Country-specific factors (India hotel average is substantially different from UK) are not used in the prototype.

5. **Missing segment IDs.** Some travel platforms do not populate a segment-level identifier in their CSV exports, only a booking-level ID. Without a segment ID, the dedup hash falls back to booking_id + expense_type, which cannot distinguish between an outbound and return flight on the same booking. A second import of the same file would skip both segments as duplicates — correct behaviour — but a file with a single booking containing two legs of the same type would conflate them.
