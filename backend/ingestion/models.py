from django.db import models
from django.contrib.auth.models import User
from core.models import Tenant


# =============================================================================
# SAP Models (Source 1 — Scope 1: Fuel & Procurement)
# =============================================================================

class PlantLookup(models.Model):
    """
    Maps opaque SAP plant codes to real-world locations.
    Populated once per client during onboarding.
    In SAP, this data lives in table T001W.

    Example: plant_code '1010' → 'Mumbai Factory', Maharashtra, India
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='plant_lookups')
    plant_code = models.CharField(max_length=10, help_text="SAP plant code (e.g. '1010')")
    company_code = models.CharField(max_length=10, help_text="SAP company code (e.g. 'IN01')")
    plant_name = models.CharField(max_length=255, help_text="Human-readable name (e.g. 'Mumbai Factory')")
    country = models.CharField(max_length=2, help_text="ISO country code (e.g. 'IN')")
    region = models.CharField(max_length=100, help_text="State/region (e.g. 'Maharashtra')")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('tenant', 'plant_code', 'company_code')
        verbose_name = 'Plant Lookup'
        verbose_name_plural = 'Plant Lookups'

    def __str__(self):
        return f"{self.plant_code} → {self.plant_name} ({self.region}, {self.country})"


class SAPIngestionBatch(models.Model):
    """
    One batch = one OData pull or manual JSON upload.
    Stores the full raw payload for audit trail and reprocessing.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sap_batches')
    ingestion_source = models.CharField(
        max_length=255,
        help_text="Source identifier — e.g. 'sap_normal.json' or 'manual_upload'"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    raw_payload = models.JSONField(help_text="Full OData JSON response, stored for audit trail")
    rows_total = models.IntegerField(default=0)
    rows_failed = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'SAP Ingestion Batch'
        verbose_name_plural = 'SAP Ingestion Batches'

    def __str__(self):
        return f"SAP Batch #{self.pk} ({self.ingestion_source}) — {self.status}"


class RawSAPRecord(models.Model):
    """
    Untouched SAP purchase order line item — exactly as received from OData.
    This is the auditor's source-of-truth. Never modified after creation.

    Fields map directly to SAP OData API_PURCHASEORDER_PROCESS_SRV response fields:
    - PurchaseOrder, PurchaseOrderItem, CompanyCode, Plant, Material,
      MaterialGroup, OrderQuantity, PurchaseOrderQuantityUnit, DocumentDate, Supplier
    """
    batch = models.ForeignKey(SAPIngestionBatch, on_delete=models.CASCADE, related_name='records')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='raw_sap_records')

    # SAP OData fields — preserved exactly as received
    purchase_order = models.CharField(max_length=20, help_text="SAP PurchaseOrder number")
    purchase_order_item = models.CharField(max_length=10, help_text="Line item within PO")
    company_code = models.CharField(max_length=10, help_text="SAP CompanyCode (e.g. 'IN01')")
    plant_code = models.CharField(max_length=10, help_text="SAP Plant code (e.g. '1010')")
    material = models.CharField(max_length=40, help_text="SAP Material number")
    material_group = models.CharField(max_length=20, help_text="Material group (e.g. 'FUEL01')")
    order_quantity = models.DecimalField(
        max_digits=15, decimal_places=3,
        help_text="Quantity ordered — raw value before unit conversion"
    )
    quantity_unit = models.CharField(max_length=10, help_text="SAP unit (L, KG, TO, GAL, etc.)")
    document_date = models.DateField(help_text="Parsed from SAP OData V2 /Date(ms)/ format")
    supplier = models.CharField(max_length=20, blank=True, default='', help_text="Vendor code")

    # Audit fields
    source_row_hash = models.CharField(
        max_length=64,
        help_text="SHA256 of plant+material+quantity+date — for duplicate detection"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Raw SAP Record'
        verbose_name_plural = 'Raw SAP Records'

    def __str__(self):
        return f"PO {self.purchase_order}/{self.purchase_order_item} — {self.material_group} {self.order_quantity}{self.quantity_unit}"


# =============================================================================
# Utility Models (Source 2 — Scope 2: Electricity)
# =============================================================================

class UtilityIngestionBatch(models.Model):
    """
    One batch = one CSV file upload from a utility portal export.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='utility_batches')
    source_file_name = models.CharField(max_length=255, help_text="Original uploaded filename")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    rows_total = models.IntegerField(default=0)
    rows_failed = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Utility Ingestion Batch'
        verbose_name_plural = 'Utility Ingestion Batches'

    def __str__(self):
        return f"Utility Batch #{self.pk} ({self.source_file_name}) — {self.status}"


class RawUtilityRecord(models.Model):
    """
    Untouched utility billing record — preserves portal-native field names.
    Cross-utility schema: nullable fields accommodate BESCOM/MSEDCL/TGSPDCL differences.

    - BESCOM uses account_id + rr_number
    - MSEDCL uses consumer_number
    - TGSPDCL/TSSPDCL uses usc_no
    - 'Units consumed' in Indian utilities = kWh
    """
    batch = models.ForeignKey(UtilityIngestionBatch, on_delete=models.CASCADE, related_name='records')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='raw_utility_records')

    # Utility identification — nullable to accommodate different utilities
    utility = models.CharField(max_length=20, help_text="Utility name: BESCOM, MSEDCL, TGSPDCL")
    account_id = models.CharField(max_length=50, blank=True, default='', help_text="BESCOM identifier")
    rr_number = models.CharField(max_length=50, blank=True, default='', help_text="BESCOM RR Number")
    consumer_number = models.CharField(max_length=50, blank=True, default='', help_text="MSEDCL identifier")
    usc_no = models.CharField(max_length=50, blank=True, default='', help_text="TGSPDCL/TSSPDCL USC No")
    consumer_name = models.CharField(max_length=255, blank=True, default='')

    # Tariff and location
    tariff = models.CharField(max_length=50, help_text="Tariff category (e.g. 'LT1', 'HT-Industry')")
    raw_tariff_label = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Preserves source-of-truth wording (e.g. 'CAT-1 Domestic')"
    )
    circle_division = models.CharField(max_length=100, blank=True, default='', help_text="Portal-derived enrichment")

    # Billing period and meter readings
    billing_period_from = models.DateField(help_text="Start of billing period")
    billing_period_to = models.DateField(help_text="End of billing period")
    previous_reading = models.DecimalField(max_digits=15, decimal_places=3)
    present_reading = models.DecimalField(max_digits=15, decimal_places=3)
    units_consumed = models.DecimalField(
        max_digits=15, decimal_places=3,
        help_text="Primary activity field — 'Units' = kWh in Indian utility context"
    )

    # Meter details — nullable because not all utilities provide all fields
    meter_constant = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        help_text="Multiplier for CT/PT connected meters. actual_kWh = reading_diff × meter_constant"
    )
    meter_status = models.CharField(
        max_length=30, blank=True, default='',
        help_text="NORMAL, Estimated, or TGSPDCL numeric codes (01, 02)"
    )
    average_units = models.DecimalField(
        max_digits=15, decimal_places=3, null=True, blank=True,
        help_text="Historical average — used for suspicious-row detection"
    )
    days_in_bill_cycle = models.IntegerField(null=True, blank=True)
    recorded_md_kw = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        help_text="Maximum demand in kW — industrial context"
    )

    # Audit fields
    source_row_hash = models.CharField(
        max_length=64,
        help_text="SHA256 of utility+meter_id+billing_from+billing_to — for duplicate detection"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Raw Utility Record'
        verbose_name_plural = 'Raw Utility Records'

    def __str__(self):
        meter_id = self.rr_number or self.consumer_number or self.usc_no or self.account_id
        return f"{self.utility} {meter_id} — {self.units_consumed} units ({self.billing_period_from} to {self.billing_period_to})"


# =============================================================================
# Travel Models (Source 3 — Scope 3: Corporate Travel, with Scope 1 for company vehicles)
# =============================================================================

class TravelIngestionBatch(models.Model):
    """
    One batch = one CSV file upload from Concur/Navan travel export.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='travel_batches')
    source_file_name = models.CharField(max_length=255, help_text="Original uploaded filename")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    rows_total = models.IntegerField(default=0)
    rows_failed = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Travel Ingestion Batch'
        verbose_name_plural = 'Travel Ingestion Batches'

    def __str__(self):
        return f"Travel Batch #{self.pk} ({self.source_file_name}) — {self.status}"


class RawTravelRecord(models.Model):
    """
    Unified schema for all 3 travel categories: flights, hotels, ground transport.
    Distinguished by expense_type column. Nullable fields vary by category.
    Modeled after Concur Trip Report / Navan booking export shape.

    Scope classification:
    - Flights → Scope 3 Category 6
    - Hotels → Scope 3 Category 6
    - Ground (company vehicle) → Scope 1 (direct combustion)
    - Ground (third party: Uber, train) → Scope 3 Category 6
    """
    EXPENSE_TYPE_CHOICES = [
        ('flight', 'Flight'),
        ('hotel', 'Hotel'),
        ('ground', 'Ground Transport'),
    ]

    batch = models.ForeignKey(TravelIngestionBatch, on_delete=models.CASCADE, related_name='records')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='raw_travel_records')

    # Common fields (all categories)
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPE_CHOICES)
    source = models.CharField(max_length=20, blank=True, default='', help_text="concur or navan")
    external_booking_id = models.CharField(max_length=50, help_text="Booking ID from travel platform")
    traveler_name = models.CharField(max_length=255)
    traveler_email = models.CharField(max_length=255, blank=True, default='')
    booking_created_at = models.DateTimeField(null=True, blank=True)
    booking_status = models.CharField(max_length=20, help_text="ticketed, confirmed, cancelled, etc.")
    fare_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=5, blank=True, default='')

    # Flight-specific fields (null for hotels/ground)
    trip_id = models.CharField(max_length=50, blank=True, default='')
    segment_id = models.CharField(max_length=10, blank=True, default='')
    carrier = models.CharField(max_length=50, blank=True, default='')
    flight_number = models.CharField(max_length=20, blank=True, default='')
    record_locator = models.CharField(max_length=20, blank=True, default='', help_text="PNR / Record Locator")
    origin_iata = models.CharField(max_length=5, blank=True, default='', help_text="Departure airport IATA code")
    destination_iata = models.CharField(max_length=5, blank=True, default='', help_text="Arrival airport IATA code")
    departure_datetime_local = models.DateTimeField(null=True, blank=True)
    arrival_datetime_local = models.DateTimeField(null=True, blank=True)
    cabin_class = models.CharField(max_length=20, blank=True, default='', help_text="economy, business, first")
    ticket_number = models.CharField(max_length=30, blank=True, default='')
    trip_type = models.CharField(max_length=20, blank=True, default='', help_text="business, personal")

    # Hotel-specific fields (null for flights/ground)
    vendor_name = models.CharField(max_length=100, blank=True, default='', help_text="Hotel name")
    city = models.CharField(max_length=100, blank=True, default='')
    country_code = models.CharField(max_length=5, blank=True, default='', help_text="ISO country code")
    check_in_date = models.DateField(null=True, blank=True)
    check_out_date = models.DateField(null=True, blank=True)
    nights = models.IntegerField(null=True, blank=True)
    rooms = models.IntegerField(null=True, blank=True)

    # Ground transport-specific fields (null for flights/hotels)
    transport_mode = models.CharField(
        max_length=30, blank=True, default='',
        help_text="car, taxi, train, bus"
    )
    provider_type = models.CharField(
        max_length=20, blank=True, default='',
        help_text="'company' = Scope 1 (direct combustion), 'third-party' = Scope 3"
    )
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    vehicle_fuel_type = models.CharField(
        max_length=20, blank=True, default='',
        help_text="diesel, petrol, electric — relevant for company vehicles"
    )
    trip_date = models.DateField(null=True, blank=True)

    # Audit fields
    source_row_hash = models.CharField(
        max_length=64,
        help_text="SHA256 of booking_id+segment_id+expense_type — for duplicate detection"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Raw Travel Record'
        verbose_name_plural = 'Raw Travel Records'

    def __str__(self):
        if self.expense_type == 'flight':
            return f"Flight {self.origin_iata}→{self.destination_iata} ({self.traveler_name})"
        elif self.expense_type == 'hotel':
            return f"Hotel {self.vendor_name}, {self.city} — {self.nights} nights ({self.traveler_name})"
        else:
            return f"Ground {self.transport_mode} {self.distance_km}km ({self.traveler_name})"


# =============================================================================
# Normalized Emission Record — The Canonical Table
# =============================================================================

class NormalizedEmissionRecord(models.Model):
    """
    Single canonical table that all 3 sources write into after normalization.
    This is the "pipe in the middle" — messy data in → clean verified emissions data out.

    Two-layer architecture:
    1. Raw records (RawSAPRecord, RawUtilityRecord, RawTravelRecord) — untouched source data
    2. This table — normalized, calculated, reviewed, and audit-locked

    Review workflow: pending → suspicious (auto-flagged) → approved/rejected → locked (immutable)

    Fields exactly match the knowledge base specification (KB L258-284).
    """
    SOURCE_TYPE_CHOICES = [
        ('sap', 'SAP'),
        ('utility', 'Utility'),
        ('travel', 'Travel'),
    ]

    SCOPE_CHOICES = [
        ('1', 'Scope 1 — Direct Emissions'),
        ('2', 'Scope 2 — Indirect (Electricity)'),
        ('3', 'Scope 3 — Value Chain'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('suspicious', 'Suspicious'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    # Identity & source tracking
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='emission_records')
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    raw_record_id = models.PositiveIntegerField(
        help_text="FK to the raw table row (generic FK pattern — no ContentType overhead)"
    )
    raw_record_type = models.CharField(
        max_length=30,
        help_text="Which raw table: 'RawSAPRecord', 'RawUtilityRecord', or 'RawTravelRecord'"
    )

    # Activity data
    activity_date = models.DateField(help_text="When the activity occurred")
    reporting_month = models.CharField(
        max_length=7,
        help_text="YYYY-MM — derived from activity_date for SAP/travel, majority-month rule for utility"
    )
    scope = models.CharField(max_length=1, choices=SCOPE_CHOICES)
    activity_description = models.CharField(
        max_length=255,
        help_text="Human-readable (e.g. 'Diesel purchase at Mumbai Factory')"
    )

    # Quantities — both original and normalized for audit trail
    quantity_normalized = models.DecimalField(
        max_digits=15, decimal_places=4,
        help_text="Converted to canonical unit (liters, kWh, km, room-nights)"
    )
    unit_normalized = models.CharField(
        max_length=20,
        help_text="Always one of: 'liters', 'kWh', 'kg', 'km', 'room-nights'"
    )
    quantity_original = models.DecimalField(
        max_digits=15, decimal_places=4,
        help_text="Raw value from source before conversion"
    )
    unit_original = models.CharField(max_length=20, help_text="Raw unit from source")

    # Emission calculation
    emission_factor = models.DecimalField(
        max_digits=10, decimal_places=6,
        help_text="Applied emission factor value"
    )
    emission_factor_source = models.CharField(
        max_length=100,
        help_text="Citation (e.g. 'DEFRA 2023', 'CEA 2023 — Karnataka')"
    )
    co2e_kg = models.DecimalField(
        max_digits=15, decimal_places=4,
        help_text="Final calculated kg CO₂e — the key number"
    )

    # Review workflow
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_locked = models.BooleanField(
        default=False,
        help_text="True = audit-safe, immutable. No endpoint can modify a locked record."
    )
    flagged_reason = models.TextField(
        blank=True, default='',
        help_text="Why auto-flagged as suspicious (empty if clean)"
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_records'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Manual edit tracking
    edited_manually = models.BooleanField(
        default=False,
        help_text="Was this record hand-edited after normalization?"
    )
    edit_note = models.TextField(
        blank=True, default='',
        help_text="Reason for manual edit — required if edited_manually=True"
    )

    # Deduplication & audit
    source_row_hash = models.CharField(
        max_length=64,
        help_text="Same hash as the raw record — enables cross-layer duplicate detection"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Normalized Emission Record'
        verbose_name_plural = 'Normalized Emission Records'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'source_type']),
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'scope']),
            models.Index(fields=['tenant', 'reporting_month']),
            models.Index(fields=['source_row_hash']),
        ]

    def __str__(self):
        return f"[{self.scope}] {self.activity_description} — {self.co2e_kg} kg CO₂e ({self.status})"
