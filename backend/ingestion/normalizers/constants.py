"""
Emission factors, unit conversions, and lookup tables.

All factors are hardcoded — this is a documented tradeoff.
See TRADEOFFS.md: "Static emission factors — hardcoded DEFRA 2023 / CEA 2023 tables.
Production needs live update pipeline from IEA/DEFRA (updated annually)."

Sources:
- SAP fuel factors: DEFRA 2023 Greenhouse Gas Conversion Factors
- Utility factors: CEA (Central Electricity Authority) CO2 Baseline Database 2023
- Travel (flight/hotel/ground): DEFRA 2023 Greenhouse Gas Conversion Factors
"""

# =============================================================================
# SAP — Unit Conversion to Canonical Units
# =============================================================================
# Canonical unit for liquid fuels = liters
# Canonical unit for solid/weight fuels = kg

SAP_UNIT_TO_LITERS = {
    # Liquid fuel units → liters
    'L': 1.0,
    'LT': 1.0,       # SAP alias for liter
    'LTR': 1.0,
    'GAL': 3.78541,  # US gallon
    'GL': 3.78541,   # SAP alias for US gallon
    'M3': 1000.0,    # cubic meter
}

SAP_UNIT_TO_KG = {
    # Weight/solid fuel units → kg
    'KG': 1.0,
    'G': 0.001,
    'TO': 1000.0,    # metric tonne (SAP standard)
    'T': 1000.0,     # alias
    'LB': 0.453592,  # pounds
}

# =============================================================================
# SAP — Emission Factors (DEFRA 2023)
# kg CO₂e per liter (for liquid fuels) or per kg (for weight-based fuels)
# =============================================================================
# MaterialGroup → (fuel_name, emission_factor, canonical_unit, factor_source)
SAP_MATERIAL_GROUP_FACTORS = {
    'FUEL01': ('Diesel',       2.6391, 'liters', 'DEFRA 2023'),
    'FUEL02': ('Petrol',       2.3122, 'liters', 'DEFRA 2023'),
    'FUEL03': ('LPG',          1.5557, 'kg',     'DEFRA 2023'),  # LPG normalized to kg
    'FUEL04': ('Furnace Oil',  2.9530, 'liters', 'DEFRA 2023'),
}

# =============================================================================
# Utility — Emission Factors (CEA 2023, State-wise)
# kg CO₂e per kWh
# Source: CEA CO2 Baseline Database Version 18.0 (2023)
# =============================================================================
# Utility name → (state, emission_factor, source_citation)
UTILITY_EMISSION_FACTORS = {
    'BESCOM':   ('Karnataka',    0.82, 'CEA 2023 — Karnataka'),
    'MSEDCL':   ('Maharashtra',  0.75, 'CEA 2023 — Maharashtra'),
    'TGSPDCL':  ('Telangana',    0.91, 'CEA 2023 — Telangana'),
    'TSSPDCL':  ('Telangana',    0.91, 'CEA 2023 — Telangana'),
}

# Fallback for unknown utility (national average — DEFRA 2023 India grid)
UTILITY_DEFAULT_FACTOR = 0.82
UTILITY_DEFAULT_SOURCE = 'CEA 2023 — Karnataka (default)'

# Meter status codes that indicate estimated readings
# TGSPDCL uses numeric codes: '01' = actual, '02' = estimated
ESTIMATED_METER_STATUSES = {'estimated', '02', 'est', 'e'}

# =============================================================================
# Travel — Flight Distances (Great Circle, km)
# Hardcoded for prototype — documented tradeoff:
# "Production needs geocoding service (airport coordinate API)"
# Source: Calculated from IATA coordinates, verified against Google Flights
# =============================================================================
FLIGHT_DISTANCES_KM = {
    # Tuple key: (origin, destination) — both sorted alphabetically for symmetry
    # get_flight_distance() uses (min(a,b), max(a,b)) so keys MUST be alpha-sorted
    ('BLR', 'BOM'): 981,    # Bengaluru ↔ Mumbai — short haul
    ('BLR', 'DEL'): 1709,   # Bengaluru ↔ Delhi — medium haul edge case (>1500km)
    ('BLR', 'HYD'): 500,    # Bengaluru ↔ Hyderabad — short haul
    ('BLR', 'JFK'): 13701,  # Bengaluru ↔ New York — long haul
    ('BLR', 'LHR'): 8180,   # Bengaluru ↔ London Heathrow — long haul
    ('BLR', 'MAA'): 291,    # Bengaluru ↔ Chennai — short haul
    ('BOM', 'DEL'): 1148,   # Mumbai ↔ Delhi — short haul
    ('BOM', 'DXB'): 1931,   # Mumbai ↔ Dubai — medium haul
    ('BOM', 'HYD'): 620,    # Hyderabad ↔ Mumbai — short haul
    ('BOM', 'LHR'): 7186,   # Mumbai ↔ London — long haul
    ('BOM', 'MAA'): 1015,   # Mumbai ↔ Chennai — short haul
    ('DEL', 'HYD'): 1253,   # Delhi ↔ Hyderabad — short haul
    ('DEL', 'LHR'): 6730,   # Delhi ↔ London — long haul
    ('DEL', 'MAA'): 1756,   # Delhi ↔ Chennai — medium haul
}


def get_flight_distance(origin: str, destination: str) -> int | None:
    """
    Look up great circle distance between two airports.
    Returns distance in km, or None if not in lookup.
    Symmetric — tries both (A, B) and (B, A).
    """
    origin = origin.upper().strip()
    destination = destination.upper().strip()
    key_ab = (min(origin, destination), max(origin, destination))
    return FLIGHT_DISTANCES_KM.get(key_ab)


# =============================================================================
# Travel — Flight Emission Factors (DEFRA 2023, WITH Radiative Forcing)
# kg CO₂e per passenger-km
#
# IMPORTANT: These factors ALREADY INCLUDE the 1.9× radiative forcing multiplier.
# DEFRA 2023 publishes two columns: "without RF" and "with RF".
# We use the "with RF" column. Do NOT multiply by RF again in normalizer code.
#
# Why: Emissions at altitude have ~1.9× the warming effect of ground-level CO₂.
# DEFRA recommends using "with RF" for corporate reporting.
# =============================================================================
# Haul band thresholds (km)
SHORT_HAUL_MAX_KM = 1500
MEDIUM_HAUL_MAX_KM = 4000
# > 4000 km = long haul

# RF is already included in these factors — do NOT apply separately
RADIATIVE_FORCING_INCLUDED = True

# (haul_band, cabin_class) → kg CO₂e per passenger-km (with RF baked in)
FLIGHT_EMISSION_FACTORS = {
    ('short',  'economy'):  0.29507,   # 0.15530 × 1.9
    ('short',  'business'): 0.44261,   # 0.23295 × 1.9
    ('short',  'first'):    0.44261,
    ('medium', 'economy'):  0.24947,   # 0.13130 × 1.9
    ('medium', 'business'): 0.49894,   # 0.26260 × 1.9
    ('medium', 'first'):    0.74841,   # 0.39390 × 1.9
    ('long',   'economy'):  0.21831,   # 0.11490 × 1.9
    ('long',   'business'): 0.81535,   # 0.42913 × 1.9
    ('long',   'first'):    0.87324,   # 0.45960 × 1.9
}


def get_haul_band(distance_km: float) -> str:
    if distance_km <= SHORT_HAUL_MAX_KM:
        return 'short'
    elif distance_km <= MEDIUM_HAUL_MAX_KM:
        return 'medium'
    else:
        return 'long'


def normalize_cabin_class(raw: str) -> str:
    """Normalize cabin class string to economy/business/first."""
    raw = raw.lower().strip()
    if raw in ('business', 'biz', 'c', 'j'):
        return 'business'
    if raw in ('first', 'f', 'a'):
        return 'first'
    return 'economy'  # default — caller should flag if raw was blank


# =============================================================================
# Travel — Hotel Emission Factors (DEFRA 2023)
# kg CO₂e per room-night
# =============================================================================
HOTEL_EMISSION_FACTORS = {
    'IN': (63.0, 'DEFRA 2023 — India'),
    'GB': (33.0, 'DEFRA 2023 — United Kingdom'),
    'US': (57.0, 'DEFRA 2023 — United States'),
    'AE': (52.0, 'DEFRA 2023 — UAE'),
    'SG': (71.0, 'DEFRA 2023 — Singapore'),
    'DE': (29.0, 'DEFRA 2023 — Germany'),
}
HOTEL_DEFAULT_FACTOR = 63.0
HOTEL_DEFAULT_SOURCE = 'DEFRA 2023 — India (default)'


# =============================================================================
# Travel — Ground Transport Emission Factors (DEFRA 2023)
# kg CO₂e per km
# =============================================================================
GROUND_EMISSION_FACTORS = {
    # mode → (factor, source)
    'car':     (0.1700, 'DEFRA 2023 — Average car'),
    'diesel':  (0.1668, 'DEFRA 2023 — Diesel car'),
    'petrol':  (0.1702, 'DEFRA 2023 — Petrol car'),
    'taxi':    (0.1490, 'DEFRA 2023 — Taxi'),
    'train':   (0.0364, 'DEFRA 2023 — National rail'),
    'bus':     (0.1027, 'DEFRA 2023 — Local bus'),
    'default': (0.1700, 'DEFRA 2023 — Average car (default)'),
}


def get_ground_factor(transport_mode: str, vehicle_fuel_type: str) -> tuple:
    """
    Returns (emission_factor, source_citation) for ground transport.
    Prefers fuel-specific factor if available, falls back to mode-based.
    """
    mode = transport_mode.lower().strip() if transport_mode else 'car'
    fuel = vehicle_fuel_type.lower().strip() if vehicle_fuel_type else ''

    # Fuel-specific overrides
    if fuel in GROUND_EMISSION_FACTORS:
        return GROUND_EMISSION_FACTORS[fuel]

    return GROUND_EMISSION_FACTORS.get(mode, GROUND_EMISSION_FACTORS['default'])
