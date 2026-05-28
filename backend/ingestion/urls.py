"""
Ingestion API URL routes.

All prefixed with /api/ (configured in config/urls.py).

Endpoints:
  POST  /api/ingest/sap/trigger/       — SAP data (generator or static file)
  POST  /api/ingest/utility/            — Utility CSV upload
  POST  /api/ingest/travel/             — Travel CSV upload
  GET   /api/records/                   — List normalized records (filterable)
  PATCH /api/records/<id>/approve/     — Approve + lock a record
  PATCH /api/records/<id>/reject/      — Reject a record
  GET   /api/batches/                  — Recent ingestion batch history
  PATCH /api/records/bulk-approve/     — Bulk approve + lock multiple records
"""

from django.urls import path
from ingestion.views import (
    SAPTriggerIngestView,
    UtilityIngestView,
    TravelIngestView,
    NormalizedRecordListView,
    ApproveRecordView,
    RejectRecordView,
    BatchHistoryView,
    BulkApproveView,
    ExportApprovedRecordsView,
)

urlpatterns = [
    # Ingestion endpoints
    path('ingest/sap/trigger/', SAPTriggerIngestView.as_view(), name='ingest-sap-trigger'),
    path('ingest/utility/', UtilityIngestView.as_view(), name='ingest-utility'),
    path('ingest/travel/', TravelIngestView.as_view(), name='ingest-travel'),

    # Records (dashboard)
    path('records/', NormalizedRecordListView.as_view(), name='records-list'),

    # Review actions — export MUST be before <int:pk> routes
    path('records/export/', ExportApprovedRecordsView.as_view(), name='records-export'),
    path('records/<int:pk>/approve/', ApproveRecordView.as_view(), name='record-approve'),
    path('records/<int:pk>/reject/', RejectRecordView.as_view(), name='record-reject'),
    path('records/bulk-approve/', BulkApproveView.as_view(), name='records-bulk-approve'),

    # Batch history
    path('batches/', BatchHistoryView.as_view(), name='batch-history'),
]
