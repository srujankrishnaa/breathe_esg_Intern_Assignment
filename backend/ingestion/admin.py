from django.contrib import admin
from .models import (
    PlantLookup,
    SAPIngestionBatch, RawSAPRecord,
    UtilityIngestionBatch, RawUtilityRecord,
    TravelIngestionBatch, RawTravelRecord,
    NormalizedEmissionRecord,
)


@admin.register(PlantLookup)
class PlantLookupAdmin(admin.ModelAdmin):
    list_display = ('plant_code', 'company_code', 'plant_name', 'region', 'country', 'tenant')
    list_filter = ('tenant', 'country')
    search_fields = ('plant_code', 'plant_name')


@admin.register(SAPIngestionBatch)
class SAPIngestionBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'tenant', 'ingestion_source', 'status', 'rows_total', 'rows_failed', 'created_at')
    list_filter = ('status', 'tenant')


@admin.register(RawSAPRecord)
class RawSAPRecordAdmin(admin.ModelAdmin):
    list_display = ('purchase_order', 'plant_code', 'material_group', 'order_quantity', 'quantity_unit', 'document_date')
    list_filter = ('material_group', 'plant_code', 'tenant')
    search_fields = ('purchase_order', 'material')


@admin.register(UtilityIngestionBatch)
class UtilityIngestionBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'tenant', 'source_file_name', 'status', 'rows_total', 'rows_failed', 'created_at')
    list_filter = ('status', 'tenant')


@admin.register(RawUtilityRecord)
class RawUtilityRecordAdmin(admin.ModelAdmin):
    list_display = ('utility', 'consumer_name', 'units_consumed', 'billing_period_from', 'billing_period_to', 'meter_status')
    list_filter = ('utility', 'meter_status', 'tenant')
    search_fields = ('consumer_name', 'account_id', 'consumer_number', 'usc_no')


@admin.register(TravelIngestionBatch)
class TravelIngestionBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'tenant', 'source_file_name', 'status', 'rows_total', 'rows_failed', 'created_at')
    list_filter = ('status', 'tenant')


@admin.register(RawTravelRecord)
class RawTravelRecordAdmin(admin.ModelAdmin):
    list_display = ('expense_type', 'traveler_name', 'booking_status', 'external_booking_id', 'created_at')
    list_filter = ('expense_type', 'booking_status', 'tenant')
    search_fields = ('traveler_name', 'external_booking_id')


@admin.register(NormalizedEmissionRecord)
class NormalizedEmissionRecordAdmin(admin.ModelAdmin):
    list_display = ('source_type', 'scope', 'activity_description', 'co2e_kg', 'status', 'is_locked', 'created_at')
    list_filter = ('source_type', 'scope', 'status', 'is_locked', 'tenant')
    search_fields = ('activity_description',)
    readonly_fields = ('source_row_hash', 'created_at')
