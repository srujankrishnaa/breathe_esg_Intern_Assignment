"""
DRF serializers for the ingestion API.

Two categories:
1. Response serializers — for returning normalized records to the frontend
2. Input handling — CSV parsing + SAP JSON done directly in views (not via serializer)

Why no input serializers for CSV/JSON ingestion?
  CSVs have nullable cross-utility columns that don't map cleanly to DRF serializer
  validation. Parsing is done in-view using Python's csv module for simplicity and
  to preserve source-native field names. SAP JSON is already validated by the
  OData structure. The normalizers handle domain validation.
"""

from rest_framework import serializers
from ingestion.models import NormalizedEmissionRecord


class NormalizedEmissionRecordSerializer(serializers.ModelSerializer):
    """
    Read serializer for dashboard display.
    Includes all fields the frontend needs:
    - Identity (source, scope)
    - Calculated values (co2e_kg, emission_factor)
    - Review state (status, is_locked, flagged_reason)
    - Audit trail (reviewed_by, reviewed_at)
    """
    ghg_category = serializers.SerializerMethodField()
    reviewed_by_username = serializers.SerializerMethodField()

    class Meta:
        model = NormalizedEmissionRecord
        fields = [
            'id',
            'source_type',
            'raw_record_id',
            'raw_record_type',
            'activity_date',
            'reporting_month',
            'scope',
            'ghg_category',
            'activity_description',
            'quantity_normalized',
            'unit_normalized',
            'quantity_original',
            'unit_original',
            'emission_factor',
            'emission_factor_source',
            'co2e_kg',
            'status',
            'is_locked',
            'flagged_reason',
            'reviewed_by_username',
            'reviewed_at',
            'edited_manually',
            'edit_note',
            'source_row_hash',
            'created_at',
        ]
        read_only_fields = fields  # All read-only — edits happen via approve/reject endpoints

    def get_ghg_category(self, obj):
        """Derive the exact GHG Protocol Category read-only label based on data properties."""
        if obj.source_type == 'sap':
            return "Scope 1 — Stationary Combustion"
        elif obj.source_type == 'utility':
            return "Scope 2 — Purchased Electricity"
        elif obj.source_type == 'travel':
            if obj.scope == '1':
                return "Scope 1 — Mobile Combustion"
            elif obj.scope == '3':
                return "Scope 3 — Cat. 6 Business Travel"
        return "Unknown Category"

    def get_reviewed_by_username(self, obj):
        """Return the username of the reviewer, not the FK ID."""
        return obj.reviewed_by.username if obj.reviewed_by else None


class IngestionBatchResponseSerializer(serializers.Serializer):
    """
    Standard response format for all 3 ingestion endpoints.
    Matches handoff spec exactly:
      {"batch_id": 1, "total": 6, "failed": 1, "suspicious": 2, "duplicates_skipped": 0}
    """
    batch_id = serializers.IntegerField()
    total = serializers.IntegerField()
    failed = serializers.IntegerField()
    suspicious = serializers.IntegerField()
    duplicates_skipped = serializers.IntegerField()

