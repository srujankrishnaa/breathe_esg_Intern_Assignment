import { useState } from 'react';
import { approveRecord, rejectRecord } from '../api';
import StatusBadge from './StatusBadge';

/**
 * RecordDetailDrawer — Slide-out panel showing full audit trail for a single record.
 *
 * Inspired by Sweep ESG's evidence-based governance: every approval decision
 * should be backed by visible source traceability, calculation transparency,
 * and data quality context.
 *
 * Four sections:
 * 1. Source Traceability — where this data came from
 * 2. Data Transformation — original → normalized quantity conversion
 * 3. Emission Calculation — factor × quantity = CO₂e breakdown
 * 4. Review Trail — who reviewed, when, lock status
 *
 * For suspicious records, adds structured breakdown with severity + action.
 */

const SOURCE_ICONS = { sap: '⛽', utility: '💡', travel: '✈️' };
const SOURCE_NAMES = { sap: 'SAP Fuel Procurement', utility: 'Utility Electricity', travel: 'Corporate Travel' };
const SCOPE_LABELS = {
  '1': 'Scope 1 — Direct Emissions',
  '2': 'Scope 2 — Indirect (Electricity)',
  '3': 'Scope 3 — Value Chain',
};

/**
 * Parse a flagged_reason string into structured analyst-facing insight.
 * Transforms raw log-style messages into what/why/action breakdown.
 */
function parseSuspiciousReason(reason) {
  if (!reason) return null;

  const lower = reason.toLowerCase();

  // Quantity anomaly
  if (lower.includes('quantity') || lower.includes('exceeds') || lower.includes('median')) {
    return {
      severity: 'warning',
      title: 'High Quantity Anomaly',
      icon: '📊',
      what: reason,
      why: 'Could indicate a bulk procurement, data entry error, or unit mismatch (e.g., liters vs gallons). Outliers above 2× the category median are auto-flagged.',
      action: 'Verify with the plant manager or cross-check the SAP purchase order document for the correct quantity and unit.',
    };
  }

  // Unknown plant
  if (lower.includes('plant') || lower.includes('unknown')) {
    return {
      severity: 'error',
      title: 'Unknown Plant Code',
      icon: '🏭',
      what: reason,
      why: 'The SAP plant code doesn\'t exist in the PlantLookup table. This means the system can\'t determine the facility location, which affects regional emission factor selection.',
      action: 'Register the plant code in the PlantLookup table via admin, or confirm with IT that the code is correct.',
    };
  }

  // Estimated meter reading
  if (lower.includes('estimated') || lower.includes('meter')) {
    return {
      severity: 'warning',
      title: 'Estimated Meter Reading',
      icon: '🔌',
      what: reason,
      why: 'The utility marked this reading as estimated rather than actual. Estimated readings are often based on historical averages and may over- or under-report actual consumption.',
      action: 'Accept if the estimate is reasonable (within ±15% of the average). Flag for re-reading in the next billing cycle.',
    };
  }

  // Billing period anomaly
  if (lower.includes('billing') || lower.includes('days') || lower.includes('period')) {
    return {
      severity: 'warning',
      title: 'Billing Period Anomaly',
      icon: '📅',
      what: reason,
      why: 'The billing period length is unusual — either too short or too long compared to standard monthly cycles. This can distort per-month emission calculations.',
      action: 'Check if the utility provider issued a catch-up bill or split billing period. Adjust the reporting month assignment if needed.',
    };
  }

  // Cancelled booking
  if (lower.includes('cancelled') || lower.includes('canceled')) {
    return {
      severity: 'error',
      title: 'Cancelled Booking',
      icon: '🚫',
      what: reason,
      why: 'Cancelled travel segments should not contribute to emissions. If this booking was later rebooked, the replacement segment should appear separately.',
      action: 'Reject this record — cancelled segments are not part of the emissions inventory.',
    };
  }

  // Missing route data
  if (lower.includes('route') || lower.includes('distance') || lower.includes('iata')) {
    return {
      severity: 'error',
      title: 'Missing Route Data',
      icon: '🗺️',
      what: reason,
      why: 'The origin or destination airport code is missing or not in the distance lookup table. Without distance, the system cannot calculate flight emissions.',
      action: 'Verify the IATA codes are correct. If the route is new, add it to the flight distance table.',
    };
  }

  // Negative value
  if (lower.includes('negative')) {
    return {
      severity: 'error',
      title: 'Negative Value Detected',
      icon: '⚠️',
      what: reason,
      why: 'Negative quantities or durations indicate a data entry error or reversed date fields (e.g., check-out before check-in).',
      action: 'Reject and request corrected data from the source system.',
    };
  }

  // Fallback — generic suspicious
  return {
    severity: 'warning',
    title: 'Data Quality Flag',
    icon: '⚠️',
    what: reason,
    why: 'This record was auto-flagged during normalization. Review the details and determine if the data is correct.',
    action: 'Inspect the original values, verify with the source, then approve or reject.',
  };
}

export default function RecordDetailDrawer({ record, onClose, onUpdate, showToast }) {
  const [actionLoading, setActionLoading] = useState(null);

  if (!record) return null;

  const co2 = parseFloat(record.co2e_kg) || 0;
  const qtyNorm = parseFloat(record.quantity_normalized) || 0;
  const qtyOrig = parseFloat(record.quantity_original) || 0;
  const ef = parseFloat(record.emission_factor) || 0;
  const suspiciousInfo = parseSuspiciousReason(record.flagged_reason);

  async function handleApprove() {
    setActionLoading('approve');
    try {
      await approveRecord(record.id);
      onUpdate();
      showToast?.('Record approved and locked');
      onClose();
    } catch (err) {
      showToast?.(err.message, 'error');
    } finally {
      setActionLoading(null);
    }
  }

  async function handleReject() {
    setActionLoading('reject');
    try {
      await rejectRecord(record.id);
      onUpdate();
      showToast?.('Record rejected');
      onClose();
    } catch (err) {
      showToast?.(err.message, 'error');
    } finally {
      setActionLoading(null);
    }
  }

  function formatCO2(val) {
    if (val >= 1000) return `${(val / 1000).toFixed(2)} tonnes`;
    return `${val.toFixed(2)} kg`;
  }

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="record-drawer">
        <div className="drawer-header">
          <div className="drawer-title-row">
            <span className="drawer-source-icon">{SOURCE_ICONS[record.source_type] || '📋'}</span>
            <div>
              <h2>Record #{record.id}</h2>
              <span className="drawer-source-label">
                {SOURCE_NAMES[record.source_type] || record.source_type}
              </span>
            </div>
          </div>
          <button className="drawer-close" onClick={onClose} title="Close drawer">✕</button>
        </div>

        <div className="drawer-body">
          {/* Status + Actions Bar */}
          <div className="drawer-status-bar">
            <div className="drawer-status-left">
              <StatusBadge status={record.status} />
              {record.is_locked && <span className="drawer-lock" title="Audit-locked — immutable">🔒 Locked</span>}
            </div>
            {!record.is_locked && (
              <div className="drawer-actions">
                <button
                  className="btn btn-approve btn-sm"
                  onClick={handleApprove}
                  disabled={actionLoading}
                >
                  {actionLoading === 'approve' ? <span className="spinner" /> : '✓ Approve & Lock'}
                </button>
                <button
                  className="btn btn-reject btn-sm"
                  onClick={handleReject}
                  disabled={actionLoading}
                >
                  ✗ Reject
                </button>
              </div>
            )}
          </div>

          {/* Suspicious Breakdown (if applicable) */}
          {suspiciousInfo && (
            <div className={`suspicious-breakdown severity-${suspiciousInfo.severity}`}>
              <div className="suspicious-header">
                <span className="suspicious-icon">{suspiciousInfo.icon}</span>
                <span className="suspicious-title">{suspiciousInfo.title}</span>
                <span className={`suspicious-severity-pill ${suspiciousInfo.severity}`}>
                  {suspiciousInfo.severity}
                </span>
              </div>
              <div className="suspicious-section">
                <label>What happened</label>
                <p>{suspiciousInfo.what}</p>
              </div>
              <div className="suspicious-section">
                <label>Why it matters</label>
                <p>{suspiciousInfo.why}</p>
              </div>
              <div className="suspicious-section">
                <label>Recommended action</label>
                <p>{suspiciousInfo.action}</p>
              </div>
            </div>
          )}

          {/* Section 1: Source Traceability */}
          <div className="drawer-section">
            <h3>📎 Source Traceability</h3>
            <div className="drawer-field-grid">
              <div className="drawer-field">
                <label>Source Type</label>
                <span>{record.source_type?.toUpperCase()}</span>
              </div>
              <div className="drawer-field">
                <label>GHG Category</label>
                <span>{record.ghg_category}</span>
              </div>
              <div className="drawer-field">
                <label>Scope</label>
                <span>{SCOPE_LABELS[record.scope] || record.scope}</span>
              </div>
              <div className="drawer-field">
                <label>Raw Record ID</label>
                <span className="mono">{record.raw_record_type} #{record.raw_record_id}</span>
              </div>
              <div className="drawer-field">
                <label>Source Row Hash</label>
                <span className="mono hash-truncate" title={record.source_row_hash}>
                  {record.source_row_hash?.substring(0, 16)}…
                </span>
              </div>
              <div className="drawer-field">
                <label>Ingested At</label>
                <span>{record.created_at ? new Date(record.created_at).toLocaleString() : '—'}</span>
              </div>
            </div>
          </div>

          {/* Section 2: Data Transformation */}
          <div className="drawer-section">
            <h3>🔄 Data Transformation</h3>
            <div className="transformation-visual">
              <div className="transform-box original">
                <label>Original (Source)</label>
                <span className="transform-value">{qtyOrig.toLocaleString()} {record.unit_original}</span>
              </div>
              <div className="transform-arrow">→</div>
              <div className="transform-box normalized">
                <label>Normalized</label>
                <span className="transform-value">{qtyNorm.toLocaleString(undefined, {maximumFractionDigits: 2})} {record.unit_normalized}</span>
              </div>
            </div>
            <div className="drawer-field-grid" style={{ marginTop: 12 }}>
              <div className="drawer-field">
                <label>Activity</label>
                <span>{record.activity_description}</span>
              </div>
              <div className="drawer-field">
                <label>Activity Date</label>
                <span>{record.activity_date}</span>
              </div>
              <div className="drawer-field">
                <label>Reporting Month</label>
                <span>{record.reporting_month}</span>
              </div>
            </div>
          </div>

          {/* Section 3: Emission Calculation */}
          <div className="drawer-section">
            <h3>🧮 Emission Calculation</h3>
            <div className="calculation-breakdown">
              <div className="calc-row">
                <span className="calc-label">Activity quantity</span>
                <span className="calc-value mono">{qtyNorm.toLocaleString(undefined, {maximumFractionDigits: 2})} {record.unit_normalized}</span>
              </div>
              <div className="calc-row">
                <span className="calc-label">× Emission factor</span>
                <span className="calc-value mono">{ef.toFixed(6)} kg CO₂e/{record.unit_normalized}</span>
              </div>
              <div className="calc-divider" />
              <div className="calc-row calc-total">
                <span className="calc-label">= Total CO₂e</span>
                <span className="calc-value mono accent">{formatCO2(co2)}</span>
              </div>
            </div>
            <div className="calc-source">
              <label>Factor source</label>
              <span>{record.emission_factor_source || '—'}</span>
            </div>
          </div>

          {/* Section 4: Review Trail */}
          <div className="drawer-section">
            <h3>📝 Review Trail</h3>
            <div className="drawer-field-grid">
              <div className="drawer-field">
                <label>Current Status</label>
                <span><StatusBadge status={record.status} /></span>
              </div>
              <div className="drawer-field">
                <label>Reviewed By</label>
                <span>{record.reviewed_by_username || '— not yet reviewed'}</span>
              </div>
              <div className="drawer-field">
                <label>Reviewed At</label>
                <span>{record.reviewed_at ? new Date(record.reviewed_at).toLocaleString() : '—'}</span>
              </div>
              <div className="drawer-field">
                <label>Audit Lock</label>
                <span>{record.is_locked ? '🔒 Locked — immutable' : '🔓 Unlocked — editable'}</span>
              </div>
              {record.edited_manually && (
                <div className="drawer-field full-width">
                  <label>Manual Edit Note</label>
                  <span>{record.edit_note || 'No note provided'}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
