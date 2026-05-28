"""
SAP normalization logic.

Takes a RawSAPRecord instance → returns a dict of NormalizedEmissionRecord fields,
or raises ValueError with a human-readable reason if the record is suspicious.

Suspicion flags (from KB):
  - Unknown plant code
  - Unknown material group
  - Unknown unit
  - Zero or negative quantity
  - Quantity > 100,000 liters (after conversion)
"""

import re
from datetime import datetime, timezone
from decimal import Decimal

from ingestion.normalizers.constants import (
    SAP_UNIT_TO_LITERS,
    SAP_UNIT_TO_KG,
    SAP_MATERIAL_GROUP_FACTORS,
)


def _parse_sap_date(date_str: str) -> datetime:
    """
    Parse SAP OData V2 date format: /Date(1704067200000)/
    Returns a Python datetime (UTC).
    Raises ValueError if format is unrecognized.
    """
    match = re.match(r'/Date\((\d+)\)/', str(date_str))
    if not match:
        raise ValueError(f"Unrecognized SAP date format: '{date_str}'")
    ms = int(match.group(1))
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def normalize_sap_record(raw_record, plant_lookup: dict) -> dict:
    """
    Normalize a RawSAPRecord into a dict of NormalizedEmissionRecord fields.

    Args:
        raw_record: RawSAPRecord model instance
        plant_lookup: dict mapping plant_code (str) → PlantLookup instance.
                      Caller builds this from PlantLookup.objects.filter(tenant=tenant).

    Returns:
        dict with all fields needed to create a NormalizedEmissionRecord

    Raises:
        ValueError: if any suspicion condition is met — caller catches and
                    creates a NormalizedEmissionRecord with status='suspicious'
    """
    flags = []  # Collect all issues — raise once at the end with combined message

    # ------------------------------------------------------------------
    # 1. Resolve plant
    # ------------------------------------------------------------------
    plant = plant_lookup.get(raw_record.plant_code)
    if plant is None:
        flags.append(f"Unknown plant code '{raw_record.plant_code}' — not in PlantLookup table")

    # ------------------------------------------------------------------
    # 2. Resolve material group → fuel type + emission factor
    # ------------------------------------------------------------------
    material_group = raw_record.material_group.upper().strip()
    if material_group not in SAP_MATERIAL_GROUP_FACTORS:
        flags.append(
            f"Unknown material group '{raw_record.material_group}' — "
            f"no emission factor available"
        )
        fuel_name, emission_factor, canonical_unit, ef_source = (
            'Unknown', Decimal('0'), 'liters', 'N/A'
        )
    else:
        fuel_name, emission_factor_float, canonical_unit, ef_source = (
            SAP_MATERIAL_GROUP_FACTORS[material_group]
        )
        emission_factor = Decimal(str(emission_factor_float))

    # ------------------------------------------------------------------
    # 3. Quantity validation
    # ------------------------------------------------------------------
    quantity_original = raw_record.order_quantity
    unit_original = raw_record.quantity_unit.upper().strip()

    if quantity_original <= 0:
        flags.append(
            f"Zero or negative quantity ({quantity_original} {unit_original}) — "
            f"likely a data entry error"
        )

    # ------------------------------------------------------------------
    # 4. Unit conversion → canonical unit
    # ------------------------------------------------------------------
    if canonical_unit == 'liters':
        if unit_original in SAP_UNIT_TO_LITERS:
            quantity_normalized = quantity_original * Decimal(
                str(SAP_UNIT_TO_LITERS[unit_original])
            )
            unit_normalized = 'liters'
        elif unit_original in SAP_UNIT_TO_KG:
            # Weight → liters isn't meaningful for most fuels
            # Flag as unknown unit if only weight conversion exists
            flags.append(
                f"Unit '{unit_original}' is weight-based but fuel '{fuel_name}' "
                f"expects volume (liters) — cannot convert accurately"
            )
            quantity_normalized = quantity_original
            unit_normalized = unit_original
        else:
            flags.append(f"Unknown unit '{unit_original}' — no conversion available")
            quantity_normalized = quantity_original
            unit_normalized = unit_original
    else:  # canonical_unit == 'kg'
        if unit_original in SAP_UNIT_TO_KG:
            quantity_normalized = quantity_original * Decimal(
                str(SAP_UNIT_TO_KG[unit_original])
            )
            unit_normalized = 'kg'
        elif unit_original in SAP_UNIT_TO_LITERS:
            flags.append(
                f"Unit '{unit_original}' is volume-based but fuel '{fuel_name}' "
                f"expects weight (kg) — cannot convert accurately"
            )
            quantity_normalized = quantity_original
            unit_normalized = unit_original
        else:
            flags.append(f"Unknown unit '{unit_original}' — no conversion available")
            quantity_normalized = quantity_original
            unit_normalized = unit_original

    # ------------------------------------------------------------------
    # 5. High quantity check (post-conversion)
    # ------------------------------------------------------------------
    if quantity_normalized > 100000 and not flags:
        # Only flag high quantity if no other issues (don't double-flag)
        flags.append(
            f"Unusually high quantity: {quantity_normalized:,.0f} {unit_normalized} "
            f"(threshold: 100,000 {unit_normalized}) — verify with source"
        )
    elif quantity_normalized > 100000:
        flags.append(
            f"Unusually high quantity: {quantity_normalized:,.0f} {unit_normalized}"
        )

    # ------------------------------------------------------------------
    # 6. Calculate CO₂e
    # ------------------------------------------------------------------
    if not flags or all('high quantity' in f for f in flags):
        # Calculate even for high quantity (suspicious but calculable)
        co2e_kg = (quantity_normalized * emission_factor).quantize(Decimal('0.0001'))
    else:
        co2e_kg = Decimal('0')

    # ------------------------------------------------------------------
    # 7. Activity date + reporting month
    # ------------------------------------------------------------------
    activity_date = raw_record.document_date
    reporting_month = activity_date.strftime('%Y-%m')

    # ------------------------------------------------------------------
    # 8. Activity description
    # ------------------------------------------------------------------
    if plant:
        location = f"{plant.plant_name} ({plant.region}, {plant.country})"
    else:
        location = f"Plant code '{raw_record.plant_code}' (unknown)"

    activity_description = f"{fuel_name} purchase at {location}"

    # ------------------------------------------------------------------
    # 9. Raise if any critical flags collected, otherwise return normalized dict
    # ------------------------------------------------------------------
    critical_flags = [f for f in flags if "high quantity" not in f]
    if critical_flags:
        raise ValueError(" | ".join(critical_flags))

    status = 'suspicious' if flags else 'pending'
    flagged_reason = " | ".join(flags) if flags else ''

    return {
        'source_type': 'sap',
        'raw_record_id': raw_record.pk,
        'raw_record_type': 'RawSAPRecord',
        'activity_date': activity_date,
        'reporting_month': reporting_month,
        'scope': '1',  # Fuel combustion = Scope 1 direct emissions
        'activity_description': activity_description,
        'quantity_normalized': quantity_normalized,
        'unit_normalized': unit_normalized,
        'quantity_original': quantity_original,
        'unit_original': raw_record.quantity_unit,
        'emission_factor': emission_factor,
        'emission_factor_source': ef_source,
        'co2e_kg': co2e_kg,
        'status': status,
        'is_locked': False,
        'flagged_reason': flagged_reason,
        'source_row_hash': raw_record.source_row_hash,
    }
