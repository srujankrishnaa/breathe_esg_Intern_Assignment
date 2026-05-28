"""
Utility (electricity) normalization logic.

Takes a RawUtilityRecord instance → returns a dict of NormalizedEmissionRecord fields,
or raises ValueError with a human-readable reason if suspicious.

Key rules (from KB):
  1. "Units" = kWh in Indian utilities (not a separate unit — it IS kWh)
  2. Billing period attribution: majority-of-days rule for cross-month periods
  3. Meter constant: actual_kWh = reading_diff × meter_constant (default 1)
  4. CEA 2023 state-wise emission factors per utility
  5. Meter status 'Estimated' or TGSPDCL code '02' → suspicious

Suspicion flags (from KB):
  - Zero consumption
  - Present reading < previous reading (meter reset)
  - Meter status = Estimated / '02'
  - Unknown utility (no emission factor available)
"""

from decimal import Decimal
from datetime import date, timedelta

from ingestion.normalizers.constants import (
    UTILITY_EMISSION_FACTORS,
    UTILITY_DEFAULT_FACTOR,
    UTILITY_DEFAULT_SOURCE,
    ESTIMATED_METER_STATUSES,
)


def _majority_month(date_from: date, date_to: date) -> str:
    """
    Determine which YYYY-MM gets this billing period assigned.

    Rule (KB L128): Assign to the month where the MAJORITY of days fall.
    If perfectly split (rare), assign to the end month.

    Example: Dec 22 – Jan 21 (31 days total)
      December: 10 days (Dec 22-31)
      January: 21 days (Jan 1-21)
      → January wins → "2026-01"
    """
    # Count days per month in [date_from, date_to)
    month_days: dict[str, int] = {}

    current = date_from
    while current < date_to:
        key = current.strftime('%Y-%m')
        month_days[key] = month_days.get(key, 0) + 1
        current += timedelta(days=1)

    if not month_days:
        # Edge case: date_from == date_to (0-day billing period)
        return date_from.strftime('%Y-%m')

    # Return the month with most days (ties go to last entry = end month)
    return max(month_days, key=lambda k: (month_days[k], k))


def normalize_utility_record(raw_record) -> dict:
    """
    Normalize a RawUtilityRecord into a dict of NormalizedEmissionRecord fields.

    Args:
        raw_record: RawUtilityRecord model instance

    Returns:
        dict with all fields needed to create a NormalizedEmissionRecord

    Raises:
        ValueError: if any suspicion condition is met
    """
    flags = []

    # Resolve meter identifier for use in flag messages
    meter_id = (
        raw_record.rr_number
        or raw_record.consumer_number
        or raw_record.usc_no
        or raw_record.account_id
        or 'unknown meter'
    )

    # ------------------------------------------------------------------
    # 1. Resolve emission factor by utility
    # ------------------------------------------------------------------
    utility = raw_record.utility.upper().strip()
    if utility in UTILITY_EMISSION_FACTORS:
        state, ef_float, ef_source = UTILITY_EMISSION_FACTORS[utility]
    else:
        flags.append(
            f"Unknown utility '{raw_record.utility}' (meter {meter_id}) — "
            f"no state-specific emission factor available, using national default"
        )
        ef_float = UTILITY_DEFAULT_FACTOR
        ef_source = UTILITY_DEFAULT_SOURCE

    emission_factor = Decimal(str(ef_float))

    # ------------------------------------------------------------------
    # 2. Meter constant — actual consumption = reading_diff × meter_constant
    # ------------------------------------------------------------------
    meter_constant = raw_record.meter_constant or Decimal('1')

    # ------------------------------------------------------------------
    # 3. Consumption calculation
    # ------------------------------------------------------------------
    units_consumed = raw_record.units_consumed

    # Zero consumption check
    if units_consumed <= 0:
        flags.append(
            f"Zero or negative consumption ({units_consumed} units) for meter {meter_id} — "
            f"possible faulty or inactive meter"
        )

    # Meter reading consistency check
    if raw_record.present_reading < raw_record.previous_reading:
        flags.append(
            f"Meter {meter_id}: present reading ({raw_record.present_reading}) < "
            f"previous reading ({raw_record.previous_reading}) — "
            f"meter may have been reset or replaced"
        )

    # Apply meter constant to get actual kWh
    # In Indian utilities: units_consumed field already accounts for meter constant
    # in most portal exports. But if meter_constant != 1, apply it.
    if meter_constant != Decimal('1'):
        actual_kwh = units_consumed * meter_constant
    else:
        actual_kwh = units_consumed

    # ------------------------------------------------------------------
    # 4. Meter status check
    # ------------------------------------------------------------------
    meter_status = (raw_record.meter_status or '').lower().strip()
    if meter_status in ESTIMATED_METER_STATUSES:
        flags.append(
            f"Meter status is estimated (status: '{raw_record.meter_status}') — "
            f"reading is an approximation, not an actual meter read"
        )

    # ------------------------------------------------------------------
    # 5. Calculate CO₂e
    # ------------------------------------------------------------------
    # "Units" = kWh in Indian utility context (KB L127)
    quantity_normalized = actual_kwh
    unit_normalized = 'kWh'
    quantity_original = units_consumed
    unit_original = 'kWh'   # Portal column is labelled "units" but the measured quantity is kWh

    if not flags or quantity_normalized > 0:
        co2e_kg = (quantity_normalized * emission_factor).quantize(Decimal('0.0001'))
    else:
        co2e_kg = Decimal('0')

    # ------------------------------------------------------------------
    # 6. Billing period attribution (majority-month rule)
    # ------------------------------------------------------------------
    reporting_month = _majority_month(
        raw_record.billing_period_from,
        raw_record.billing_period_to
    )
    activity_date = raw_record.billing_period_from

    # ------------------------------------------------------------------
    # 7. Activity description
    # ------------------------------------------------------------------
    meter_id = (
        raw_record.rr_number
        or raw_record.consumer_number
        or raw_record.usc_no
        or raw_record.account_id
        or 'unknown meter'
    )
    activity_description = (
        f"Electricity — {raw_record.utility} meter {meter_id} "
        f"({raw_record.billing_period_from} to {raw_record.billing_period_to})"
    )

    # ------------------------------------------------------------------
    # 8. Raise if critical flags, otherwise return normalized dict
    # ------------------------------------------------------------------
    critical_flags = [
        f for f in flags
        if "faulty or inactive meter" in f or "meter may have been reset" in f
    ]
    if critical_flags:
        raise ValueError(" | ".join(critical_flags))

    status = 'suspicious' if flags else 'pending'
    flagged_reason = " | ".join(flags) if flags else ''

    return {
        'source_type': 'utility',
        'raw_record_id': raw_record.pk,
        'raw_record_type': 'RawUtilityRecord',
        'activity_date': activity_date,
        'reporting_month': reporting_month,
        'scope': '2',  # Purchased electricity = Scope 2
        'activity_description': activity_description,
        'quantity_normalized': quantity_normalized,
        'unit_normalized': unit_normalized,
        'quantity_original': quantity_original,
        'unit_original': unit_original,
        'emission_factor': emission_factor,
        'emission_factor_source': ef_source,
        'co2e_kg': co2e_kg,
        'status': status,
        'is_locked': False,
        'flagged_reason': flagged_reason,
        'source_row_hash': raw_record.source_row_hash,
    }
