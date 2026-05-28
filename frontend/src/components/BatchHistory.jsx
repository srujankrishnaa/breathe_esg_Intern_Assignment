import { useState, useEffect } from 'react';
import { fetchBatches } from '../api';

/**
 * BatchHistory — Sidebar component showing recent ingestion batches.
 *
 * Sweep ESG's raw layer is all about batch-level traceability.
 * This component gives the analyst a timeline of when data came in,
 * from which source, and what the success rate per batch was.
 *
 * Clicking a batch could filter the dashboard (future enhancement).
 */

const SOURCE_ICONS = { sap: '⛽', utility: '💡', travel: '✈️' };
const SOURCE_COLORS = {
  sap: 'var(--scope1)',
  utility: 'var(--scope2)',
  travel: 'var(--scope3)',
};

function timeAgo(isoString) {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function BatchHistory() {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    fetchBatches()
      .then(data => setBatches(Array.isArray(data) ? data : []))
      .catch(() => setBatches([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="sidebar-card">
        <div className="sidebar-card-header">
          <h3>Ingestion History</h3>
          <p className="sidebar-desc">Loading...</p>
        </div>
      </div>
    );
  }

  if (batches.length === 0) {
    return (
      <div className="sidebar-card">
        <div className="sidebar-card-header">
          <h3>Ingestion History</h3>
          <p className="sidebar-desc">No batches yet — ingest data to see history</p>
        </div>
      </div>
    );
  }

  return (
    <div className="sidebar-card batch-history-card">
      <div className="sidebar-card-header clickable" onClick={() => setCollapsed(!collapsed)}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
          <div>
            <h3>Ingestion History</h3>
            <p className="sidebar-desc">{batches.length} recent batch{batches.length !== 1 ? 'es' : ''}</p>
          </div>
          <span className="batch-collapse-icon">{collapsed ? '▼' : '▲'}</span>
        </div>
      </div>

      {!collapsed && (
        <div className="batch-timeline">
          {batches.map(batch => {
            const successRate = batch.rows_total > 0
              ? Math.round(((batch.rows_total - batch.rows_failed) / batch.rows_total) * 100)
              : 100;

            return (
              <div key={`${batch.source_type}-${batch.id}`} className="batch-item">
                <div className="batch-item-header">
                  <span
                    className="batch-item-icon"
                    style={{ color: SOURCE_COLORS[batch.source_type] }}
                  >
                    {SOURCE_ICONS[batch.source_type] || '📦'}
                  </span>
                  <div className="batch-item-info">
                    <span className="batch-item-label" title={batch.source_label}>
                      {batch.source_label?.length > 24
                        ? batch.source_label.substring(0, 24) + '…'
                        : batch.source_label}
                    </span>
                    <span className="batch-item-time">{timeAgo(batch.created_at)}</span>
                  </div>
                </div>
                <div className="batch-item-stats">
                  <span className="batch-stat">{batch.rows_total} rows</span>
                  {batch.rows_suspicious > 0 && (
                    <span className="batch-stat batch-stat-warn">⚠ {batch.rows_suspicious}</span>
                  )}
                  {batch.rows_failed > 0 && (
                    <span className="batch-stat batch-stat-error">✗ {batch.rows_failed}</span>
                  )}
                  <span
                    className={`batch-rate ${successRate === 100 ? 'perfect' : successRate >= 80 ? 'good' : 'low'}`}
                  >
                    {successRate}%
                  </span>
                </div>
                {/* Mini progress bar */}
                <div className="batch-progress">
                  <div
                    className="batch-progress-fill"
                    style={{
                      width: `${successRate}%`,
                      background: successRate === 100
                        ? 'var(--accent)'
                        : successRate >= 80
                          ? 'var(--status-pending)'
                          : 'var(--status-rejected)',
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
