# REVIEW PREP
## Likely Questions and How to Answer Them
**Private — do not submit. For the post-submission review call.**

---

## Data Model (35% of grade — expect deep questions here)

**"Why did you use a generic FK instead of Django ContentTypes?"**
Three source types, fixed at design time. ContentType adds a dependency and a DB join on every FK resolution for no benefit when the set of related models is known and small. A CharField holding the class name is readable, filterable, and resolved in a dict lookup.

**"Why is reporting_month a CharField and not a DateField?"**
It's a period label, not a point in time. Forcing day=1 into a DateField implies precision that doesn't exist — a billing cycle from Jan 18 to Feb 19 belongs to February, not to 2026-02-01. CharField stores exactly what it represents.

**"Why is is_locked the hard boundary and not status?"**
Status is a business-layer label that communicates state to the analyst. is_locked is the audit-layer enforcement mechanism. If a future bug inadvertently changes status, is_locked=True still blocks modification. The two fields serve different layers; always check the stronger constraint first.

**"Why does reviewed_by use on_delete=SET_NULL?"**
Deleting a user account must not cascade to emission records they approved — those records may already be in an audit submission. SET_NULL preserves the record with the FK nulled. The username is recoverable from the serializer's reviewed_by_username field.

**"Why does the multi-tenancy scaffold exist if only one tenant is used?"**
Retrofitting tenant isolation onto an existing schema requires touching every query. The constraint is cheap to add early and expensive to add late. The scaffold is present; it is not exercised beyond one tenant in this prototype.

**"Walk me through the audit trail for a single emission record."**
Source → raw record (exact data as received, never modified) → NormalizedEmissionRecord (source_type, raw_record_id, raw_record_type point back to the raw row) → emission_factor + emission_factor_source show what was applied → reviewed_by + reviewed_at show who signed off → is_locked=True shows when it was locked for audit. Every question an auditor can ask has a field that answers it.

---

## Scope Classification (high chance of being tested)

**"How do you determine scope for ground transport?"**
provider_type field, not expense_type. company_vehicle → Scope 1 (direct combustion, company asset). third_party (taxi, Uber, train) → Scope 3 (purchased service). Both appear as "ground" by expense type but the asset ownership is different.

**"Why is electricity Scope 2 and not Scope 1?"**
Scope 1 is direct combustion of fuels the company controls. Scope 2 is purchased energy — the company does not own the generation asset. Electricity from the grid is Scope 2 by GHG Protocol definition regardless of how it was generated.

**"Why are hotel stays Scope 3?"**
Hotels are third-party properties. The company does not own or operate them. Under GHG Protocol, business travel (including accommodation) is a Scope 3 Category 6 activity.

---

## SAP Source

**"Why OData and not IDoc or BAPI?"**
OData V2 via SAP Gateway is the format most enterprise IT teams can expose without custom development. It returns JSON. IDoc requires ALE/EDI configuration that most clients haven't set up for data extraction. BAPI requires RFC-capable connectors adding infrastructure dependencies. OData was the lowest-friction choice for a new client onboarding scenario.

**"What happens if the plant code in the SAP data doesn't exist in your lookup table?"**
The normalizer flags the record as suspicious and stores the reason in flagged_reason. The record is created with status=suspicious and co2e_kg=0. The analyst sees it on the dashboard and can investigate — either the plant code is a data entry error in SAP, or PlantLookup needs a new row added.

**"What is the /Date(ms)/ format and why does it look like that?"**
OData V2 JSON serialization quirk. Dates are encoded as milliseconds since Unix epoch wrapped in that string — e.g. /Date(1704067200000)/ for 2024-01-01. OData V4 (S/4HANA) uses ISO 8601 instead. The parser extracts the integer, divides by 1000, and converts to a Python date via datetime.fromtimestamp.

**"Why can't LPG use volume units?"**
LPG is sold by weight in India — suppliers invoice in kilograms. A volume-to-kg conversion requires density data that varies with temperature and pressure, which is not present in a purchase order. Giving LPG a volume unit would require assumptions the data doesn't support. The generator enforces KG/TO only for FUEL03.

---

## Utility Source

**"Why four different identifier fields for utility accounts?"**
Each DISCOM uses a different name for the same concept. BESCOM calls it rr_number, MSEDCL calls it consumer_number, TGSPDCL calls it usc_no. Coercing them into a single field loses source fidelity and makes the origin utility ambiguous. The normalizer resolves whichever is populated.

**"How do you handle a billing period that crosses two months?"**
Majority month attribution. Count the days falling in each calendar month; the month with more days gets the record. A cycle from Jan 18 to Feb 19 is 14 days in January and 19 days in February — reporting_month = 2026-02.

**"What is a meter_constant and why does it matter?"**
CT (Current Transformer) metered connections — used for large industrial loads — measure a fraction of the actual current. The CT ratio (e.g. 40:1) multiplies the difference in readings to get actual consumption. Ignoring it produces consumption figures that are 40-200x too low. A plant consuming 10,000 kWh would appear to consume 250 kWh.

**"What emission factor did you use for electricity and why?"**
CEA (Central Electricity Authority) 2022-23 national grid emission factor for India: 0.716 kg CO₂e per kWh. CEA is the authoritative source for Indian grid factors, published annually. The national average is used because state-level factors require mapping each DISCOM to a regional grid, which is additional configuration not in this prototype scope.

---

## Travel Source

**"How do you calculate flight emissions without distance in the data?"**
IATA origin and destination codes are always in the booking data. A hardcoded lookup table maps known route pairs to distances in km. For unknown routes (codes present but pair not in the lookup), the record is flagged as suspicious. A production implementation would query an IATA distance API or compute great-circle distance from airport coordinates.

**"Why does cabin class matter for flight emissions?"**
DEFRA 2023 emission factors vary significantly by class: economy is 0.155 kg CO₂e/pkm, business is 0.428 kg CO₂e/pkm, first is 0.597 kg CO₂e/pkm. A business class flight emits roughly 2.8x more per passenger than economy. The booking data always includes cabin class so this distinction can always be applied.

**"What is radiative forcing and did you apply it?"**
Aviation causes warming beyond CO₂ alone — contrails, NOx, and water vapour at altitude have additional warming effects. The radiative forcing factor (1.9x) accounts for this. DEFRA 2023 flight factors already include this multiplier baked into the values. The constants file documents RADIATIVE_FORCING_INCLUDED = True. Applying an additional 1.9x multiplier would double-count it.

**"What happens with cancelled flights?"**
The normalizer flags them as suspicious. A cancelled booking has zero actual travel so it should not contribute to the emissions record — but it needs analyst confirmation rather than silent exclusion, because some clients want visibility into cancelled trips as a policy signal.

---

## Deliberate Tradeoffs (10% — know these cold)

**"You said no RBAC — what's the specific audit risk?"**
Separation of duties. The person who ingests data can approve their own ingestion. Most ESG assurance frameworks (GHG Protocol, ISO 14064) require that input and sign-off are performed by different people. This is a known control gap, deliberately deferred for the prototype.

**"Your emission factors are hardcoded. When do they go stale?"**
CEA publishes updated national grid factors annually, typically Q3 of the following year. DEFRA publishes updated conversion factors each June. There is no reprocessing pipeline — if factors change, historical records cannot be updated without a separate backfill operation against the raw records. This is the cost of the cut.

**"You only handle OData V2. What's the first client scenario that breaks?"**
A client running SAP S/4HANA Cloud, which uses OData V4 with ISO 8601 dates. The /Date(ms)/ parser would silently produce null dates. Second scenario: a client with a German-language SAP configuration where column headers are Bestellmenge, Buchungsdatum instead of OrderQuantity, DocumentDate.

---

## Things to Say If You Don't Know

- "I'd need to check the specific CEA state-level factor for that region — I used the national average and noted it as a gap in SOURCES.md."
- "That would require a change to the emission factor constants — I deliberately kept them hardcoded and documented that as a tradeoff."
- "That's one of the questions I'd ask the PM before finalising the schema — it's in DECISIONS.md under unanswered questions."

Do not say "the AI suggested it." If you can't explain a decision, say you made a deliberate choice and walk through the reasoning even if it's incomplete. Owning a decision you can partially defend is better than disowning one you can't.
