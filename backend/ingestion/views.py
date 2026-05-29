"""
Ingestion API views.

Endpoints:
  POST /api/ingest/sap/trigger/     — Fetch SAP data (generator or static file)
  POST /api/ingest/utility/         — Upload utility CSV
  POST /api/ingest/travel/          — Upload travel CSV
  GET  /api/records/                — List normalized records (with filters)
  PATCH /api/records/<id>/approve/  — Approve a record (locks it)
  PATCH /api/records/<id>/reject/   — Reject a record

All ingestion views follow the same pipeline:
  1. Create batch
  2. Parse source data → create raw records (with hash dedup)
  3. Run normalizer → create NormalizedEmissionRecord
  4. Return consistent response shape
"""

import csv
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import UserProfile
from ingestion.models import (
    PlantLookup,
    SAPIngestionBatch, RawSAPRecord,
    UtilityIngestionBatch, RawUtilityRecord,
    TravelIngestionBatch, RawTravelRecord,
    NormalizedEmissionRecord,
)
from ingestion.normalizers.sap import normalize_sap_record, _parse_sap_date
from ingestion.normalizers.utility import normalize_utility_record
from ingestion.normalizers.travel import normalize_travel_record
from ingestion.serializers import (
    NormalizedEmissionRecordSerializer,
    IngestionBatchResponseSerializer,
)


def _get_tenant(request):
    """Get the tenant for the authenticated user."""
    try:
        profile = UserProfile.objects.select_related('tenant').get(user=request.user)
        return profile.tenant
    except UserProfile.DoesNotExist:
        return None


def _compute_hash(*fields) -> str:
    """SHA256 hash of concatenated fields — for duplicate detection."""
    raw = '|'.join(str(f) for f in fields)
    return hashlib.sha256(raw.encode()).hexdigest()


def _create_normalized_record(tenant, normalizer_fn, raw_record, **normalizer_kwargs):
    """
    Shared helper: run normalizer, create NormalizedEmissionRecord.

    Returns tuple: (record, status_str)
      - status_str: 'created' or 'failed'

    If the normalizer raises ValueError, the exception propagates up to the
    caller's except block where it counts as rows_failed. We do NOT create
    zombie NormalizedEmissionRecords with zeroed-out fields — a ValueError
    means something structurally wrong, not a suspicious-but-calculable record.
    """
    normalized = normalizer_fn(raw_record, **normalizer_kwargs)
    record = NormalizedEmissionRecord.objects.create(
        tenant=tenant,
        **normalized
    )
    return record, 'created'


# =============================================================================
# SAP Ingestion
# =============================================================================

ALLOWED_SAP_FILES = {'sap_unknown_plant', 'sap_high_quantity'}


class SAPTriggerIngestView(APIView):
    """
    POST /api/ingest/sap/trigger/
    POST /api/ingest/sap/trigger/?file=sap_unknown_plant

    Default (no ?file=): generates fresh SAP data using the dynamic generator.
    With ?file= param: reads a static mock file for error scenario testing.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = _get_tenant(request)
        if not tenant:
            return Response(
                {'error': 'User has no tenant assigned'},
                status=status.HTTP_403_FORBIDDEN
            )

        file_param = request.query_params.get('file', '').strip()

        if file_param:
            # Static file path — validate against whitelist (prevent path traversal)
            if file_param not in ALLOWED_SAP_FILES:
                return Response(
                    {'error': f"Invalid file: '{file_param}'. Allowed: {sorted(ALLOWED_SAP_FILES)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            file_path = settings.MOCK_DATA_DIR / 'sap' / f'{file_param}.json'
            try:
                with open(file_path, 'r') as f:
                    payload = json.load(f)
            except FileNotFoundError:
                return Response(
                    {'error': f"File not found: {file_param}.json"},
                    status=status.HTTP_404_NOT_FOUND
                )
            ingestion_source = f'{file_param}.json'
        else:
            # Default: dynamic generator — fresh data every call
            from ingestion.mock_generators.sap_generator import generate_sap_payload
            payload = generate_sap_payload(num_rows=6)
            ingestion_source = 'dynamic_generator'

        items = payload.get('value', [])
        if not items:
            return Response(
                {'error': 'Payload contains no records (empty "value" array)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create batch
        batch = SAPIngestionBatch.objects.create(
            tenant=tenant,
            ingestion_source=ingestion_source,
            status='processing',
            raw_payload=payload,
            rows_total=len(items),
        )

        # Build plant lookup dict for normalizer
        plant_lookup = {
            p.plant_code: p
            for p in PlantLookup.objects.filter(tenant=tenant)
        }

        rows_created = 0
        rows_failed = 0
        rows_suspicious = 0
        duplicates_skipped = 0
        failed_rows = []

        for item_idx, item in enumerate(items):
            try:
                # Parse SAP date
                doc_date_raw = item.get('DocumentDate', '')
                match = re.match(r'/Date\((\d+)\)/', str(doc_date_raw))
                if match:
                    doc_date = datetime.fromtimestamp(
                        int(match.group(1)) / 1000, tz=timezone.utc
                    ).date()
                else:
                    doc_date = dj_timezone.now().date()

                quantity = Decimal(str(item.get('OrderQuantity', '0')))

                # Compute dedup hash
                row_hash = _compute_hash(
                    item.get('Plant', ''),
                    item.get('MaterialGroup', ''),
                    str(quantity),
                    str(doc_date),
                    item.get('PurchaseOrder', ''),
                    item.get('PurchaseOrderItem', ''),
                )

                # Check for duplicate against raw table (not normalized)
                if RawSAPRecord.objects.filter(
                    tenant=tenant, source_row_hash=row_hash
                ).exists():
                    duplicates_skipped += 1
                    continue

                # Create raw record
                raw = RawSAPRecord.objects.create(
                    batch=batch,
                    tenant=tenant,
                    purchase_order=item.get('PurchaseOrder', ''),
                    purchase_order_item=item.get('PurchaseOrderItem', ''),
                    company_code=item.get('CompanyCode', ''),
                    plant_code=item.get('Plant', ''),
                    material=item.get('Material', ''),
                    material_group=item.get('MaterialGroup', ''),
                    order_quantity=quantity,
                    quantity_unit=item.get('PurchaseOrderQuantityUnit', ''),
                    document_date=doc_date,
                    supplier=item.get('Supplier', ''),
                    source_row_hash=row_hash,
                )

                # Normalize
                record, _ = _create_normalized_record(
                    tenant, normalize_sap_record, raw, plant_lookup=plant_lookup
                )
                if record.status == 'suspicious':
                    rows_suspicious += 1
                rows_created += 1

            except ValueError as e:
                logger.warning('SAP row normalization failed (ValueError): %s', e)
                rows_failed += 1
                failed_rows.append({
                    'row': item_idx + 1,
                    'reason': str(e),
                    'source_field': item.get('MaterialGroup', 'unknown'),
                })
            except Exception as e:
                logger.exception('SAP row ingestion unexpected error: %s', e)
                rows_failed += 1
                failed_rows.append({
                    'row': item_idx + 1,
                    'reason': f'Unexpected error: {str(e)}',
                    'source_field': 'unknown',
                })

        # Update batch
        batch.rows_failed = rows_failed
        batch.status = 'done'
        batch.save()

        response_data = {
            'batch_id': batch.pk,
            'total': len(items),
            'failed': rows_failed,
            'suspicious': rows_suspicious,
            'duplicates_skipped': duplicates_skipped,
            'failed_rows': failed_rows,
        }
        return Response(response_data, status=status.HTTP_201_CREATED)


# =============================================================================
# Utility Ingestion
# =============================================================================

class UtilityIngestView(APIView):
    """
    POST /api/ingest/utility/
    Accepts a CSV file upload in the request body.

    CSV header must match the 19-column cross-utility schema from KB L138.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = _get_tenant(request)
        if not tenant:
            return Response(
                {'error': 'User has no tenant assigned'},
                status=status.HTTP_403_FORBIDDEN
            )

        csv_file = request.FILES.get('file')
        if not csv_file:
            return Response(
                {'error': 'No file uploaded. Send a CSV file with key "file".'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Read and decode CSV
        try:
            content = csv_file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
        except Exception as e:
            return Response(
                {'error': f'Failed to parse CSV: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not rows:
            return Response(
                {'error': 'CSV file contains no data rows'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create batch
        batch = UtilityIngestionBatch.objects.create(
            tenant=tenant,
            source_file_name=csv_file.name,
            status='processing',
            rows_total=len(rows),
        )

        rows_created = 0
        rows_failed = 0
        rows_suspicious = 0
        duplicates_skipped = 0
        failed_rows = []

        for row_idx, row in enumerate(rows):
            try:
                # Compute dedup hash
                meter_id = (
                    row.get('rr_number', '').strip()
                    or row.get('consumer_number', '').strip()
                    or row.get('usc_no', '').strip()
                    or row.get('account_id', '').strip()
                )
                row_hash = _compute_hash(
                    row.get('utility', '').strip(),
                    meter_id,
                    row.get('billing_period_from', '').strip(),
                    row.get('billing_period_to', '').strip(),
                )

                # Check for duplicate against raw table (not normalized)
                if RawUtilityRecord.objects.filter(
                    tenant=tenant, source_row_hash=row_hash
                ).exists():
                    duplicates_skipped += 1
                    continue

                # Parse fields with safe defaults
                def safe_decimal(val, default='0'):
                    try:
                        return Decimal(val.strip()) if val and val.strip() else Decimal(default)
                    except (InvalidOperation, AttributeError):
                        return Decimal(default)

                def safe_int(val, default=None):
                    try:
                        return int(val.strip()) if val and val.strip() else default
                    except (ValueError, AttributeError):
                        return default

                from datetime import date as date_type

                def safe_date(val):
                    if not val or not val.strip():
                        return None
                    return date_type.fromisoformat(val.strip())

                # Create raw record
                raw = RawUtilityRecord.objects.create(
                    batch=batch,
                    tenant=tenant,
                    utility=row.get('utility', '').strip(),
                    account_id=row.get('account_id', '').strip(),
                    rr_number=row.get('rr_number', '').strip(),
                    consumer_number=row.get('consumer_number', '').strip(),
                    usc_no=row.get('usc_no', '').strip(),
                    consumer_name=row.get('consumer_name', '').strip(),
                    tariff=row.get('tariff', '').strip(),
                    raw_tariff_label=row.get('raw_tariff_label', '').strip(),
                    circle_division=row.get('circle_division', '').strip(),
                    billing_period_from=safe_date(row.get('billing_period_from')),
                    billing_period_to=safe_date(row.get('billing_period_to')),
                    previous_reading=safe_decimal(row.get('previous_reading')),
                    present_reading=safe_decimal(row.get('present_reading')),
                    units_consumed=safe_decimal(row.get('units_consumed')),
                    meter_constant=safe_decimal(row.get('meter_constant')) if row.get('meter_constant', '').strip() else None,
                    meter_status=row.get('meter_status', '').strip(),
                    average_units=safe_decimal(row.get('average_units')) if row.get('average_units', '').strip() else None,
                    days_in_bill_cycle=safe_int(row.get('days_in_bill_cycle')),
                    recorded_md_kw=safe_decimal(row.get('recorded_md_kw')) if row.get('recorded_md_kw', '').strip() else None,
                    source_row_hash=row_hash,
                )

                # Normalize
                record, _ = _create_normalized_record(
                    tenant, normalize_utility_record, raw
                )
                if record.status == 'suspicious':
                    rows_suspicious += 1
                rows_created += 1

            except ValueError as e:
                logger.warning('Utility row normalization failed (ValueError): %s', e)
                rows_failed += 1
                failed_rows.append({
                    'row': row_idx + 1,
                    'reason': str(e),
                    'source_field': row.get('utility', 'unknown'),
                })
            except Exception as e:
                logger.exception('Utility row ingestion unexpected error: %s', e)
                rows_failed += 1
                failed_rows.append({
                    'row': row_idx + 1,
                    'reason': f'Unexpected error: {str(e)}',
                    'source_field': 'unknown',
                })

        # Update batch
        batch.rows_failed = rows_failed
        batch.status = 'done'
        batch.save()

        response_data = {
            'batch_id': batch.pk,
            'total': len(rows),
            'failed': rows_failed,
            'suspicious': rows_suspicious,
            'duplicates_skipped': duplicates_skipped,
            'failed_rows': failed_rows,
        }
        return Response(response_data, status=status.HTTP_201_CREATED)


# =============================================================================
# Travel Ingestion
# =============================================================================

class TravelIngestView(APIView):
    """
    POST /api/ingest/travel/
    Accepts a CSV file upload containing flight, hotel, and/or ground transport rows.
    Rows are distinguished by the `expense_type` column.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = _get_tenant(request)
        if not tenant:
            return Response(
                {'error': 'User has no tenant assigned'},
                status=status.HTTP_403_FORBIDDEN
            )

        csv_file = request.FILES.get('file')
        if not csv_file:
            return Response(
                {'error': 'No file uploaded. Send a CSV file with key "file".'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            content = csv_file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
        except Exception as e:
            return Response(
                {'error': f'Failed to parse CSV: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not rows:
            return Response(
                {'error': 'CSV file contains no data rows'},
                status=status.HTTP_400_BAD_REQUEST
            )

        batch = TravelIngestionBatch.objects.create(
            tenant=tenant,
            source_file_name=csv_file.name,
            status='processing',
            rows_total=len(rows),
        )

        rows_created = 0
        rows_failed = 0
        rows_suspicious = 0
        duplicates_skipped = 0
        failed_rows = []

        for row_idx, row in enumerate(rows):
            try:
                # Compute dedup hash
                row_hash = _compute_hash(
                    row.get('external_booking_id', '').strip(),
                    row.get('segment_id', '').strip(),
                    row.get('expense_type', '').strip(),
                )

                # Check for duplicate against raw table (not normalized)
                if RawTravelRecord.objects.filter(
                    tenant=tenant, source_row_hash=row_hash
                ).exists():
                    duplicates_skipped += 1
                    continue

                # Safe parsers
                def safe_decimal(val, default='0'):
                    try:
                        return Decimal(val.strip()) if val and val.strip() else Decimal(default)
                    except (InvalidOperation, AttributeError):
                        return Decimal(default)

                def safe_int(val, default=None):
                    try:
                        return int(val.strip()) if val and val.strip() else default
                    except (ValueError, AttributeError):
                        return default

                from datetime import date as date_type

                def safe_date(val):
                    if not val or not val.strip():
                        return None
                    return date_type.fromisoformat(val.strip())

                def safe_datetime(val):
                    if not val or not val.strip():
                        return None
                    dt = datetime.fromisoformat(val.strip())
                    # Make timezone-aware if naive (Django USE_TZ=True)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt

                # Create raw record
                raw = RawTravelRecord.objects.create(
                    batch=batch,
                    tenant=tenant,
                    # Common fields
                    expense_type=row.get('expense_type', '').strip(),
                    source=row.get('source', '').strip(),
                    external_booking_id=row.get('external_booking_id', '').strip(),
                    traveler_name=row.get('traveler_name', '').strip(),
                    traveler_email=row.get('traveler_email', '').strip(),
                    booking_created_at=safe_datetime(row.get('booking_created_at')),
                    booking_status=row.get('booking_status', '').strip(),
                    fare_amount=safe_decimal(row.get('fare_amount')) if row.get('fare_amount', '').strip() else None,
                    currency=row.get('currency', '').strip(),
                    # Flight fields
                    trip_id=row.get('trip_id', '').strip(),
                    segment_id=row.get('segment_id', '').strip(),
                    carrier=row.get('carrier', '').strip(),
                    flight_number=row.get('flight_number', '').strip(),
                    record_locator=row.get('record_locator', '').strip(),
                    origin_iata=row.get('origin_iata', '').strip(),
                    destination_iata=row.get('destination_iata', '').strip(),
                    departure_datetime_local=safe_datetime(row.get('departure_datetime_local')),
                    arrival_datetime_local=safe_datetime(row.get('arrival_datetime_local')),
                    cabin_class=row.get('cabin_class', '').strip(),
                    ticket_number=row.get('ticket_number', '').strip(),
                    trip_type=row.get('trip_type', '').strip(),
                    # Hotel fields
                    vendor_name=row.get('vendor_name', '').strip(),
                    city=row.get('city', '').strip(),
                    country_code=row.get('country_code', '').strip(),
                    check_in_date=safe_date(row.get('check_in_date')),
                    check_out_date=safe_date(row.get('check_out_date')),
                    nights=safe_int(row.get('nights')),
                    rooms=safe_int(row.get('rooms')),
                    # Ground fields
                    transport_mode=row.get('transport_mode', '').strip(),
                    provider_type=row.get('provider_type', '').strip(),
                    distance_km=safe_decimal(row.get('distance_km')) if row.get('distance_km', '').strip() else None,
                    vehicle_fuel_type=row.get('vehicle_fuel_type', '').strip(),
                    trip_date=safe_date(row.get('trip_date')),
                    # Audit
                    source_row_hash=row_hash,
                )

                # Normalize
                record, _ = _create_normalized_record(
                    tenant, normalize_travel_record, raw
                )
                if record.status == 'suspicious':
                    rows_suspicious += 1
                rows_created += 1

            except ValueError as e:
                logger.warning('Travel row normalization failed (ValueError): %s', e)
                rows_failed += 1
                failed_rows.append({
                    'row': row_idx + 1,
                    'reason': str(e),
                    'source_field': row.get('expense_type', 'unknown'),
                })
            except Exception as e:
                logger.exception('Travel row ingestion unexpected error: %s', e)
                rows_failed += 1
                failed_rows.append({
                    'row': row_idx + 1,
                    'reason': f'Unexpected error: {str(e)}',
                    'source_field': 'unknown',
                })

        # Update batch
        batch.rows_failed = rows_failed
        batch.status = 'done'
        batch.save()

        response_data = {
            'batch_id': batch.pk,
            'total': len(rows),
            'failed': rows_failed,
            'suspicious': rows_suspicious,
            'duplicates_skipped': duplicates_skipped,
            'failed_rows': failed_rows,
        }
        return Response(response_data, status=status.HTTP_201_CREATED)


# =============================================================================
# Records List (Dashboard)
# =============================================================================

class NormalizedRecordListView(ListAPIView):
    """
    GET /api/records/
    GET /api/records/?source_type=sap&scope=1&status=pending&date_from=2026-01-01&date_to=2026-03-31

    Returns all normalized emission records for the authenticated user's tenant.
    Supports filtering by source_type, scope, status, date_from, and date_to.
    Results are ordered by -created_at (newest first).
    """
    serializer_class = NormalizedEmissionRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tenant = _get_tenant(self.request)
        if not tenant:
            return NormalizedEmissionRecord.objects.none()

        qs = NormalizedEmissionRecord.objects.filter(tenant=tenant).order_by('-created_at')

        # Apply filters from query params
        source_type = self.request.query_params.get('source_type')
        if source_type:
            qs = qs.filter(source_type=source_type)

        scope = self.request.query_params.get('scope')
        if scope:
            qs = qs.filter(scope=scope)

        record_status = self.request.query_params.get('status')
        if record_status:
            qs = qs.filter(status=record_status)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            qs = qs.filter(activity_date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            qs = qs.filter(activity_date__lte=date_to)

        return qs


# =============================================================================
# Approve / Reject
# =============================================================================

class ApproveRecordView(APIView):
    """
    PATCH /api/records/<id>/approve/

    Sets status='approved', is_locked=True, and records who approved it.
    Locked records cannot be modified by any endpoint.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        tenant = _get_tenant(request)
        if not tenant:
            return Response(
                {'error': 'User has no tenant assigned'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            record = NormalizedEmissionRecord.objects.get(pk=pk, tenant=tenant)
        except NormalizedEmissionRecord.DoesNotExist:
            return Response(
                {'error': 'Record not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if record.is_locked:
            return Response(
                {'error': 'Record is locked and cannot be modified'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if record.status == 'rejected':
            return Response(
                {'error': 'Cannot approve a rejected record'},
                status=status.HTTP_400_BAD_REQUEST
            )

        record.status = 'approved'
        record.is_locked = True
        record.reviewed_by = request.user
        record.reviewed_at = dj_timezone.now()
        record.save()

        serializer = NormalizedEmissionRecordSerializer(record)
        return Response(serializer.data)


class RejectRecordView(APIView):
    """
    PATCH /api/records/<id>/reject/

    Sets status='rejected'. Does NOT lock — rejected records can be
    re-reviewed if the rejection was a mistake.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        tenant = _get_tenant(request)
        if not tenant:
            return Response(
                {'error': 'User has no tenant assigned'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            record = NormalizedEmissionRecord.objects.get(pk=pk, tenant=tenant)
        except NormalizedEmissionRecord.DoesNotExist:
            return Response(
                {'error': 'Record not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if record.is_locked:
            return Response(
                {'error': 'Record is locked and cannot be modified'},
                status=status.HTTP_400_BAD_REQUEST
            )

        record.status = 'rejected'
        record.reviewed_by = request.user
        record.reviewed_at = dj_timezone.now()
        record.save()

        serializer = NormalizedEmissionRecordSerializer(record)
        return Response(serializer.data)


# =============================================================================
# Batch History (sidebar)
# =============================================================================

class BatchHistoryView(APIView):
    """
    GET /api/batches/

    Returns recent ingestion batches across all 3 source types for the
    authenticated user's tenant. Used by the Review Dashboard sidebar
    to show ingestion timeline with success rates.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = _get_tenant(request)
        if not tenant:
            return Response([], status=status.HTTP_200_OK)

        batches = []

        # SAP batches
        for b in SAPIngestionBatch.objects.filter(tenant=tenant).order_by('-created_at')[:10]:
            suspicious_count = NormalizedEmissionRecord.objects.filter(
                tenant=tenant,
                source_type='sap',
                created_at__gte=b.created_at,
                status='suspicious',
            ).count()
            batches.append({
                'id': b.pk,
                'source_type': 'sap',
                'source_label': b.ingestion_source,
                'status': b.status,
                'rows_total': b.rows_total,
                'rows_failed': b.rows_failed,
                'rows_suspicious': suspicious_count,
                'created_at': b.created_at.isoformat(),
            })

        # Utility batches
        for b in UtilityIngestionBatch.objects.filter(tenant=tenant).order_by('-created_at')[:10]:
            suspicious_count = NormalizedEmissionRecord.objects.filter(
                tenant=tenant,
                source_type='utility',
                created_at__gte=b.created_at,
                status='suspicious',
            ).count()
            batches.append({
                'id': b.pk,
                'source_type': 'utility',
                'source_label': b.source_file_name,
                'status': b.status,
                'rows_total': b.rows_total,
                'rows_failed': b.rows_failed,
                'rows_suspicious': suspicious_count,
                'created_at': b.created_at.isoformat(),
            })

        # Travel batches
        for b in TravelIngestionBatch.objects.filter(tenant=tenant).order_by('-created_at')[:10]:
            suspicious_count = NormalizedEmissionRecord.objects.filter(
                tenant=tenant,
                source_type='travel',
                created_at__gte=b.created_at,
                status='suspicious',
            ).count()
            batches.append({
                'id': b.pk,
                'source_type': 'travel',
                'source_label': b.source_file_name,
                'status': b.status,
                'rows_total': b.rows_total,
                'rows_failed': b.rows_failed,
                'rows_suspicious': suspicious_count,
                'created_at': b.created_at.isoformat(),
            })

        # Sort all batches by created_at descending, take last 20
        batches.sort(key=lambda x: x['created_at'], reverse=True)
        return Response(batches[:20], status=status.HTTP_200_OK)


# =============================================================================
# Bulk Approve
# =============================================================================

class BulkApproveView(APIView):
    """
    PATCH /api/records/bulk-approve/

    Accepts {"ids": [1, 2, 3]} and approves + locks all non-locked,
    non-rejected records in the list. Only approves records belonging
    to the authenticated user's tenant.

    Returns summary: {"approved": 3, "skipped": 1, "details": [...]}
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        tenant = _get_tenant(request)
        if not tenant:
            return Response(
                {'error': 'User has no tenant assigned'},
                status=status.HTTP_403_FORBIDDEN
            )

        ids = request.data.get('ids', [])
        if not ids or not isinstance(ids, list):
            return Response(
                {'error': 'Provide a list of record IDs: {"ids": [1, 2, 3]}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        approved_count = 0
        skipped_count = 0
        details = []

        records = NormalizedEmissionRecord.objects.filter(
            pk__in=ids, tenant=tenant
        )

        for record in records:
            if record.is_locked:
                skipped_count += 1
                details.append({'id': record.pk, 'status': 'skipped', 'reason': 'Already locked'})
                continue
            if record.status == 'rejected':
                skipped_count += 1
                details.append({'id': record.pk, 'status': 'skipped', 'reason': 'Rejected record'})
                continue

            record.status = 'approved'
            record.is_locked = True
            record.reviewed_by = request.user
            record.reviewed_at = dj_timezone.now()
            record.save()
            approved_count += 1
            details.append({'id': record.pk, 'status': 'approved'})

        return Response({
            'approved': approved_count,
            'skipped': skipped_count,
            'details': details,
        }, status=status.HTTP_200_OK)


# =============================================================================
# Export: Audit-Ready Emissions Inventory
# =============================================================================

class ExportApprovedRecordsView(APIView):
    """
    GET /api/records/export/

    Returns a CSV of approved, locked records only — the audit-ready
    emissions inventory. This is what gets submitted to an auditor,
    into a CDP disclosure, or a BRSR filing.

    Only approved+locked records are included.
    Pending, suspicious, and rejected records are excluded by design.

    Ordered by scope → source_type → activity_date so the output
    reads as a structured GHG inventory (Scope 1 first, then 2, then 3).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse as DjangoHttpResponse

        tenant = _get_tenant(request)
        if not tenant:
            return Response(
                {'error': 'User has no tenant assigned'},
                status=status.HTTP_403_FORBIDDEN
            )

        records = NormalizedEmissionRecord.objects.filter(
            tenant=tenant,
            status='approved',
            is_locked=True,
        ).select_related('reviewed_by').order_by('scope', 'source_type', 'activity_date')

        response = DjangoHttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="emissions_inventory_{tenant.slug}.csv"'
        )
        # Allow browser download when frontend is on a different port
        response['Access-Control-Expose-Headers'] = 'Content-Disposition'

        writer = csv.writer(response)

        # Header row
        writer.writerow([
            'GHG Scope',
            'GHG Category',
            'Source',
            'Activity Description',
            'Activity Date',
            'Reporting Month',
            'Quantity (Original)',
            'Unit (Original)',
            'Quantity (Normalized)',
            'Unit (Normalized)',
            'Emission Factor',
            'Factor Source',
            'CO2e (kg)',
            'Raw Record Type',
            'Raw Record ID',
            'Reviewed By',
            'Reviewed At',
            'Source Row Hash',
        ])

        def get_ghg_category(r):
            if r.source_type == 'sap':
                return 'Scope 1 — Stationary Combustion'
            if r.source_type == 'utility':
                return 'Scope 2 — Purchased Electricity'
            if r.source_type == 'travel':
                if r.scope == '1':
                    return 'Scope 1 — Mobile Combustion'
                return 'Scope 3 — Cat. 6 Business Travel'
            return 'Unknown'

        for r in records:
            writer.writerow([
                f'Scope {r.scope}',
                get_ghg_category(r),
                r.source_type.upper(),
                r.activity_description,
                r.activity_date,
                r.reporting_month,
                r.quantity_original,
                r.unit_original,
                r.quantity_normalized,
                r.unit_normalized,
                r.emission_factor,
                r.emission_factor_source,
                r.co2e_kg,
                r.raw_record_type,
                r.raw_record_id,
                r.reviewed_by.username if r.reviewed_by else '',
                r.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if r.reviewed_at else '',
                r.source_row_hash,
            ])

        return response
