"""
Travel normalization logic.

Takes a RawTravelRecord instance → returns a dict of NormalizedEmissionRecord fields,
or raises ValueError with a human-readable reason if suspicious.

Routes by expense_type:
  - 'flight'  → _normalize_flight()
  - 'hotel'   → _normalize_hotel()
  - 'ground'  → _normalize_ground()

Scope rules (KB L226):
  - Flights → Scope 3 Category 6
  - Hotels → Scope 3 Category 6
  - Ground (provider_type='company') → Scope 1
  - Ground (provider_type='third-party') → Scope 3

Suspicion flags (from KB):
  Flights: missing airport code, unknown IATA, blank cabin class, cancelled status
  Hotels: negative nights, zero rooms
  Ground: missing distance
"""

from decimal import Decimal

from ingestion.normalizers.constants import (
    get_flight_distance,
    get_haul_band,
    normalize_cabin_class,
    FLIGHT_EMISSION_FACTORS,
    HOTEL_EMISSION_FACTORS,
    HOTEL_DEFAULT_FACTOR,
    HOTEL_DEFAULT_SOURCE,
    get_ground_factor,
)

# Booking statuses that mean the trip didn't happen → flag, don't calculate
CANCELLED_STATUSES = {'cancelled', 'canceled', 'void', 'voided', 'unused', 'refunded'}


def normalize_travel_record(raw_record) -> dict:
    """
    Route to the correct normalizer based on expense_type.

    Args:
        raw_record: RawTravelRecord model instance

    Returns:
        dict with all fields needed to create a NormalizedEmissionRecord

    Raises:
        ValueError: if any suspicion condition is met
    """
    expense_type = raw_record.expense_type.lower().strip()

    if expense_type == 'flight':
        return _normalize_flight(raw_record)
    elif expense_type == 'hotel':
        return _normalize_hotel(raw_record)
    elif expense_type == 'ground':
        return _normalize_ground(raw_record)
    else:
        raise ValueError(
            f"Unknown expense_type '{raw_record.expense_type}' — "
            f"expected: flight, hotel, or ground"
        )


def _normalize_flight(raw_record) -> dict:
    """
    Normalize a flight segment.

    Emission = distance × EF(haul_band, cabin_class)
    Note: DEFRA 2023 factors already include 1.9× radiative forcing (RF).
    Do NOT multiply by RF again — see constants.py RADIATIVE_FORCING_INCLUDED.
    """
    flags = []

    # ------------------------------------------------------------------
    # 1. Cancelled check — flag first, skip calculation
    # ------------------------------------------------------------------
    booking_status = (raw_record.booking_status or '').lower().strip()
    is_cancelled = booking_status in CANCELLED_STATUSES
    if is_cancelled:
        flags.append(
            f"{raw_record.traveler_name} — booking {raw_record.external_booking_id or 'unknown'} "
            f"has status '{raw_record.booking_status}'. "
            f"Voided/cancelled trips did not take place and must not count toward emissions. "
            f"Remove from the export or re-book and re-upload."
        )

    # ------------------------------------------------------------------
    # 2. Airport codes
    # ------------------------------------------------------------------
    origin = (raw_record.origin_iata or '').strip()
    destination = (raw_record.destination_iata or '').strip()

    has_missing_codes = False
    if not origin:
        flags.append(
            f"{raw_record.traveler_name} — origin airport code is blank "
            f"(booking {raw_record.external_booking_id or 'unknown'}). "
            f"Check the travel system export: the origin_iata column must contain a valid 3-letter IATA code."
        )
        has_missing_codes = True
    if not destination:
        flags.append(
            f"{raw_record.traveler_name} — destination airport code is blank "
            f"(booking {raw_record.external_booking_id or 'unknown'}). "
            f"Check the travel system export: the destination_iata column must contain a valid 3-letter IATA code."
        )
        has_missing_codes = True

    # ------------------------------------------------------------------
    # 3. Distance lookup
    # ------------------------------------------------------------------
    distance_km = None
    has_unknown_route = False
    if origin and destination:
        distance_km = get_flight_distance(origin, destination)
        if distance_km is None:
            has_unknown_route = True
            flags.append(
                f"{raw_record.traveler_name} — route {origin}\u2192{destination} is not in the "
                f"flight distance database (booking {raw_record.external_booking_id or 'unknown'}). "
                f"Add this route pair to the distance table, or contact the ESG team to "
                f"register the airport pair before re-uploading."
            )

    # ------------------------------------------------------------------
    # 4. Cabin class
    # ------------------------------------------------------------------
    raw_cabin = (raw_record.cabin_class or '').strip()

    if not raw_cabin:
        flags.append(
            f"{raw_record.traveler_name} — cabin class is not recorded for "
            f"{origin or '?'}\u2192{destination or '?'} "
            f"(booking {raw_record.external_booking_id or 'unknown'}). "
            f"Defaulting to economy — if actual class was business or first, "
            f"actual emissions will be higher than calculated."
        )
        cabin_normalized = 'economy'
    else:
        cabin_normalized = normalize_cabin_class(raw_cabin)

    # ------------------------------------------------------------------
    # 5. Calculate emissions
    # Can calculate only if: not cancelled, have both airports, route is known
    # ------------------------------------------------------------------
    can_calculate = (
        not is_cancelled
        and not has_missing_codes
        and not has_unknown_route
        and distance_km is not None
    )

    if can_calculate:
        haul_band = get_haul_band(distance_km)
        ef_key = (haul_band, cabin_normalized)
        ef_float = FLIGHT_EMISSION_FACTORS.get(ef_key, FLIGHT_EMISSION_FACTORS[('medium', 'economy')])
        emission_factor = Decimal(str(ef_float))

        quantity_normalized = Decimal(str(distance_km))
        # RF already baked into FLIGHT_EMISSION_FACTORS — do NOT multiply again
        co2e_kg = (quantity_normalized * emission_factor).quantize(Decimal('0.0001'))
        ef_source = f"DEFRA 2023 — {haul_band} haul, {cabin_normalized} (with RF)"
    else:
        emission_factor = Decimal('0')
        ef_source = 'N/A — could not calculate'
        quantity_normalized = Decimal(str(distance_km)) if distance_km else Decimal('0')
        co2e_kg = Decimal('0')

    # ------------------------------------------------------------------
    # 6. Activity date + description
    # ------------------------------------------------------------------
    if raw_record.departure_datetime_local:
        activity_date = raw_record.departure_datetime_local.date()
    elif raw_record.trip_date:
        activity_date = raw_record.trip_date
    else:
        activity_date = (
            raw_record.booking_created_at.date()
            if raw_record.booking_created_at else None
        )
        if not activity_date:
            flags.append(
                f"{raw_record.traveler_name} — flight date could not be determined "
                f"(booking {raw_record.external_booking_id or 'unknown'}): "
                f"departure_datetime and trip_date are both blank. "
                f"Provide at least one date field to assign this record to a reporting month."
            )

    reporting_month = activity_date.strftime('%Y-%m') if activity_date else 'unknown'

    activity_description = (
        f"Flight {origin or '?'}→{destination or '?'} "
        f"({cabin_normalized}) — {raw_record.traveler_name}"
    )

    critical_flags = [
        f for f in flags
        if "cancelled/unused" in f
        or "Missing origin" in f
        or "Missing destination" in f
        or "Unknown route" in f
        or "Cannot determine flight date" in f
    ]
    if critical_flags:
        raise ValueError(" | ".join(critical_flags))

    status = 'suspicious' if flags else 'pending'
    flagged_reason = " | ".join(flags) if flags else ''

    return {
        'source_type': 'travel',
        'raw_record_id': raw_record.pk,
        'raw_record_type': 'RawTravelRecord',
        'activity_date': activity_date,
        'reporting_month': reporting_month,
        'scope': '3',
        'activity_description': activity_description,
        'quantity_normalized': quantity_normalized,
        'unit_normalized': 'km',
        'quantity_original': quantity_normalized,
        'unit_original': 'km',
        'emission_factor': emission_factor,
        'emission_factor_source': ef_source,
        'co2e_kg': co2e_kg,
        'status': status,
        'is_locked': False,
        'flagged_reason': flagged_reason,
        'source_row_hash': raw_record.source_row_hash,
    }


def _normalize_hotel(raw_record) -> dict:
    """
    Normalize a hotel booking.

    Emission = rooms × nights × EF(country_code)
    """
    flags = []

    # ------------------------------------------------------------------
    # 1. Validate nights and rooms
    # ------------------------------------------------------------------
    nights = raw_record.nights
    rooms = raw_record.rooms or 1

    if nights is None:
        flags.append(
            f"{raw_record.traveler_name} — nights field is missing for "
            f"{raw_record.vendor_name or 'hotel'} in {raw_record.city or 'unknown city'} "
            f"(booking {raw_record.external_booking_id or 'unknown'}). "
            f"Check-out date may be blank — hotel emissions require a valid stay duration."
        )
        nights = 0

    if nights < 0:
        flags.append(
            f"{raw_record.traveler_name} — check-out date is before check-in date at "
            f"{raw_record.vendor_name or 'hotel'} (nights = {nights}). "
            f"This is a data entry error in the travel system — correct the dates and re-upload."
        )

    if nights == 0:
        flags.append(
            f"{raw_record.traveler_name} — zero nights recorded at "
            f"{raw_record.vendor_name or 'hotel'} in {raw_record.city or 'unknown city'} "
            f"(booking {raw_record.external_booking_id or 'unknown'}). "
            f"Booking may have been cancelled or check-out date equals check-in date."
        )

    # ------------------------------------------------------------------
    # 2. Country emission factor
    # ------------------------------------------------------------------
    country_code = (raw_record.country_code or '').upper().strip()
    if country_code in HOTEL_EMISSION_FACTORS:
        ef_float, ef_source = HOTEL_EMISSION_FACTORS[country_code]
    else:
        ef_float, ef_source = HOTEL_DEFAULT_FACTOR, HOTEL_DEFAULT_SOURCE
        if country_code:
            flags.append(
                f"No hotel emission factor available for country '{country_code}' "
                f"({raw_record.vendor_name or 'hotel'}, {raw_record.city or 'unknown city'}) — "
                f"using India national average ({HOTEL_DEFAULT_FACTOR} kg CO\u2082e/room-night) as fallback. "
                f"Add the country factor to improve accuracy."
            )

    emission_factor = Decimal(str(ef_float))

    # ------------------------------------------------------------------
    # 3. Calculate
    # ------------------------------------------------------------------
    room_nights = Decimal(str(max(nights, 0))) * Decimal(str(rooms))
    co2e_kg = (room_nights * emission_factor).quantize(Decimal('0.0001'))

    # ------------------------------------------------------------------
    # 4. Activity date
    # ------------------------------------------------------------------
    activity_date = raw_record.check_in_date
    if not activity_date and raw_record.trip_date:
        activity_date = raw_record.trip_date
    if not activity_date:
        flags.append(
            f"{raw_record.traveler_name} — check-in date is missing for "
            f"{raw_record.vendor_name or 'hotel'} in {raw_record.city or 'unknown city'} "
            f"(booking {raw_record.external_booking_id or 'unknown'}). "
            f"A check-in date is required to attribute emissions to a reporting month — "
            f"add check_in_date to this row and re-upload."
        )

    reporting_month = activity_date.strftime('%Y-%m') if activity_date else 'unknown'

    activity_description = (
        f"Hotel — {raw_record.vendor_name or 'Unknown'}, "
        f"{raw_record.city or 'Unknown city'}, {country_code or 'Unknown country'} "
        f"({nights} nights × {rooms} room) — {raw_record.traveler_name}"
    )

    critical_flags = [
        f for f in flags
        if "missing" in f
        or "Negative nights" in f
        or "Zero nights" in f
        or "Cannot determine hotel check-in" in f
    ]
    if critical_flags:
        raise ValueError(" | ".join(critical_flags))

    status = 'suspicious' if flags else 'pending'
    flagged_reason = " | ".join(flags) if flags else ''

    return {
        'source_type': 'travel',
        'raw_record_id': raw_record.pk,
        'raw_record_type': 'RawTravelRecord',
        'activity_date': activity_date,
        'reporting_month': reporting_month,
        'scope': '3',
        'activity_description': activity_description,
        'quantity_normalized': room_nights,
        'unit_normalized': 'room-nights',
        'quantity_original': Decimal(str(nights)),
        'unit_original': 'nights',
        'emission_factor': emission_factor,
        'emission_factor_source': ef_source,
        'co2e_kg': co2e_kg,
        'status': status,
        'is_locked': False,
        'flagged_reason': flagged_reason,
        'source_row_hash': raw_record.source_row_hash,
    }


def _normalize_ground(raw_record) -> dict:
    """
    Normalize ground transport.

    Scope rule (KB L226):
      provider_type='company' → Scope 1 (direct combustion — company owns the vehicle)
      provider_type='third-party' → Scope 3 (Uber, train, rental)

    Emission = distance_km × EF(mode, fuel_type)
    """
    flags = []

    # ------------------------------------------------------------------
    # 1. Distance
    # ------------------------------------------------------------------
    distance_km = raw_record.distance_km
    distance_display = f"{distance_km} km" if distance_km is not None else "not provided"
    if not distance_km or distance_km <= 0:
        flags.append(
            f"{raw_record.traveler_name} — distance is {distance_display} for "
            f"{raw_record.transport_mode or 'ground transport'} trip "
            f"(booking {raw_record.external_booking_id or 'unknown'}). "
            f"The distance_km column must have a positive value to calculate emissions — "
            f"check the travel system export or enter the distance manually."
        )

    # ------------------------------------------------------------------
    # 2. Scope classification
    # ------------------------------------------------------------------
    provider_type = (raw_record.provider_type or '').lower().strip()
    if provider_type == 'company':
        scope = '1'  # Company vehicle — direct combustion
        scope_note = 'Scope 1 — company vehicle (direct combustion)'
    else:
        scope = '3'  # Third-party transport
        scope_note = 'Scope 3 — third-party transport'

    # ------------------------------------------------------------------
    # 3. Emission factor
    # ------------------------------------------------------------------
    transport_mode = raw_record.transport_mode or ''
    vehicle_fuel_type = raw_record.vehicle_fuel_type or ''
    ef_float, ef_source = get_ground_factor(transport_mode, vehicle_fuel_type)
    emission_factor = Decimal(str(ef_float))

    # ------------------------------------------------------------------
    # 4. Calculate
    # ------------------------------------------------------------------
    if distance_km and distance_km > 0:
        quantity_normalized = distance_km
        co2e_kg = (quantity_normalized * emission_factor).quantize(Decimal('0.0001'))
    else:
        quantity_normalized = Decimal('0')
        co2e_kg = Decimal('0')

    # ------------------------------------------------------------------
    # 5. Activity date
    # ------------------------------------------------------------------
    activity_date = raw_record.trip_date
    if not activity_date and raw_record.booking_created_at:
        activity_date = raw_record.booking_created_at.date()

    reporting_month = activity_date.strftime('%Y-%m') if activity_date else 'unknown'

    activity_description = (
        f"Ground transport — {transport_mode or 'unknown mode'} "
        f"({distance_km or 0} km, {scope_note}) — {raw_record.traveler_name}"
    )

    if flags:
        raise ValueError(" | ".join(flags))

    return {
        'source_type': 'travel',
        'raw_record_id': raw_record.pk,
        'raw_record_type': 'RawTravelRecord',
        'activity_date': activity_date,
        'reporting_month': reporting_month,
        'scope': scope,
        'activity_description': activity_description,
        'quantity_normalized': quantity_normalized,
        'unit_normalized': 'km',
        'quantity_original': distance_km or Decimal('0'),
        'unit_original': 'km',
        'emission_factor': emission_factor,
        'emission_factor_source': ef_source,
        'co2e_kg': co2e_kg,
        'status': 'pending',
        'is_locked': False,
        'flagged_reason': '',
        'source_row_hash': raw_record.source_row_hash,
    }
