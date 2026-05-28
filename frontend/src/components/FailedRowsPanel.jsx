import { useState } from 'react';

/**
 * FailedRowsPanel — Shows rows that failed during ingestion.
 *
 * This is the component that addresses the biggest gap vs Sweep ESG:
 * failed rows currently vanish into Django server logs. This panel
 * makes them visible to the analyst so they know what data was lost
 * and why.
 *
 * Failed rows are passed via React state from the IngestPage after
 * each ingestion call. They are NOT persisted in the database (prototype
 * trade-off documented in DECISIONS.md).
 *
 * Props:
 *  - failedRows: Array of { source_type, batch_id, rows: [{ row, reason, source_field }] }
 */

export default function FailedRowsPanel({ failedRows = [] }) {
  const [expanded, setExpanded] = useState(false);

  // Filter out empty batches
  const batches = failedRows.filter(b => b.rows && b.rows.length > 0);
  const totalFailed = batches.reduce((sum, b) => sum + b.rows.length, 0);

  if (totalFailed === 0) return null;

  return (
    <div className="failed-rows-panel">
      <button
        className="failed-rows-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="failed-rows-header">
          <span className="failed-rows-icon">🚫</span>
          <div className="failed-rows-title-group">
            <span className="failed-rows-title">
              {totalFailed} Row{totalFailed !== 1 ? 's' : ''} Rejected at Ingestion
            </span>
            <span className="failed-rows-subtitle">
              These rows failed validation and were not imported
            </span>
          </div>
          <span className="failed-rows-count">{totalFailed}</span>
        </div>
        <span className="failed-rows-chevron">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="failed-rows-body">
          {batches.map((batch, bIdx) => (
            <div key={bIdx} className="failed-batch-group">
              <div className="failed-batch-header">
                <span className={`failed-batch-source badge badge-${batch.source_type}`}>
                  {batch.source_type}
                </span>
                <span className="failed-batch-label">
                  Batch #{batch.batch_id}
                </span>
              </div>
              <div className="failed-batch-rows">
                {batch.rows.map((row, rIdx) => (
                  <div key={rIdx} className="failed-row-item">
                    <div className="failed-row-header">
                      <span className="failed-row-number">Row {row.row}</span>
                      {row.source_field && row.source_field !== 'unknown' && (
                        <span className="failed-row-field">{row.source_field}</span>
                      )}
                    </div>
                    <p className="failed-row-reason">{row.reason}</p>
                  </div>
                ))}
              </div>
            </div>
          ))}
          <div className="failed-rows-footer">
            <p>
              💡 Failed rows were <strong>not imported</strong> into the emissions inventory.
              Fix the source data and re-upload to include them.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
