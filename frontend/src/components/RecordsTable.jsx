import { useState } from 'react';
import { approveRecord, rejectRecord, bulkApprove } from '../api';
import StatusBadge from './StatusBadge';
import FlaggedReason from './FlaggedReason';

const SCOPE_BADGES = { '1': 'badge-scope1', '2': 'badge-scope2', '3': 'badge-scope3' };
const SOURCE_BADGES = {
  sap: 'badge-sap',
  utility: 'badge-utility',
  travel: 'badge-travel',
};

function formatCO2(val) {
  const num = parseFloat(val);
  if (isNaN(num)) return '—';
  if (num >= 1000) return `${(num / 1000).toFixed(2)}t`;
  return `${num.toFixed(2)} kg`;
}

export default function RecordsTable({ records, onUpdate, showToast, onRowClick }) {
  const [actionLoading, setActionLoading] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);

  async function handleApprove(e, id) {
    e.stopPropagation(); // Don't open drawer
    setActionLoading(id);
    try {
      await approveRecord(id);
      onUpdate();
      showToast?.('Record approved and locked');
    } catch (err) {
      showToast?.(err.message, 'error');
    } finally {
      setActionLoading(null);
    }
  }

  async function handleReject(e, id) {
    e.stopPropagation(); // Don't open drawer
    setActionLoading(id);
    try {
      await rejectRecord(id);
      onUpdate();
      showToast?.('Record rejected');
    } catch (err) {
      showToast?.(err.message, 'error');
    } finally {
      setActionLoading(null);
    }
  }

  function toggleSelect(e, id) {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    const approvable = records.filter(r => !r.is_locked && r.status !== 'rejected');
    if (selectedIds.size === approvable.length && approvable.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(approvable.map(r => r.id)));
    }
  }

  async function handleBulkApprove() {
    if (selectedIds.size === 0) return;
    setBulkLoading(true);
    try {
      const result = await bulkApprove([...selectedIds]);
      onUpdate();
      setSelectedIds(new Set());
      showToast?.(`${result.approved} record${result.approved !== 1 ? 's' : ''} approved and locked`);
    } catch (err) {
      showToast?.(err.message, 'error');
    } finally {
      setBulkLoading(false);
    }
  }

  if (!records || records.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">📊</div>
        <p>No emission records yet. Ingest some data above to get started.</p>
      </div>
    );
  }

  const approvableCount = records.filter(r => !r.is_locked && r.status !== 'rejected').length;
  const allSelected = approvableCount > 0 && selectedIds.size === approvableCount;

  return (
    <>
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th style={{ width: 40 }}>
                <input
                  type="checkbox"
                  className="row-checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  title={allSelected ? 'Deselect all' : 'Select all approvable'}
                />
              </th>
              <th>Source</th>
              <th>GHG Category</th>
              <th>Activity</th>
              <th>Date</th>
              <th>Quantity</th>
              <th>CO₂e</th>
              <th>Factor</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {records.map(r => {
              const isSelected = selectedIds.has(r.id);
              const isApprovable = !r.is_locked && r.status !== 'rejected';

              return (
                <tr
                  key={r.id}
                  className={`record-row ${isSelected ? 'row-selected' : ''} ${r.status === 'suspicious' ? 'row-suspicious' : ''}`}
                  onClick={() => onRowClick?.(r)}
                  style={{ cursor: 'pointer', animation: 'fadeIn 0.3s ease' }}
                >
                  <td onClick={e => e.stopPropagation()}>
                    {isApprovable && (
                      <input
                        type="checkbox"
                        className="row-checkbox"
                        checked={isSelected}
                        onChange={e => toggleSelect(e, r.id)}
                      />
                    )}
                    {r.is_locked && <span style={{ fontSize: '0.7rem', opacity: 0.5 }}>🔒</span>}
                  </td>
                  <td>
                    <span className={`badge ${SOURCE_BADGES[r.source_type] || ''}`}>
                      {r.source_type}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${SCOPE_BADGES[r.scope] || ''}`} style={{ textTransform: 'none', fontWeight: 500, letterSpacing: 'normal' }}>
                      {r.ghg_category}
                    </span>
                  </td>
                  <td>
                    <div className="activity-cell" title={r.activity_description}>
                      {r.activity_description}
                    </div>
                    <FlaggedReason reason={r.flagged_reason} />
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>{r.activity_date}</td>
                  <td className="co2-value" style={{ whiteSpace: 'nowrap' }}>
                    <span title={`Original: ${parseFloat(r.quantity_original).toFixed(1)} ${r.unit_original}`}>
                      {parseFloat(r.quantity_normalized).toFixed(1)} {r.unit_normalized}
                    </span>
                  </td>
                  <td className="co2-value">{formatCO2(r.co2e_kg)}</td>
                  <td>
                    <span
                      className="ef-source-chip"
                      title={`${r.emission_factor_source} — ${parseFloat(r.emission_factor).toFixed(6)} kg CO₂e/${r.unit_normalized}`}
                    >
                      {r.emission_factor_source?.split(' ')[0] || '—'}
                    </span>
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td onClick={e => e.stopPropagation()}>
                    {/* Show actions on ANY non-locked record.
                        Rejected records are NOT locked and can be re-reviewed. */}
                    {!r.is_locked && (
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button
                          className="btn btn-approve btn-sm"
                          onClick={e => handleApprove(e, r.id)}
                          disabled={actionLoading === r.id}
                          title="Approve — locks this record permanently"
                        >
                          {actionLoading === r.id ? <span className="spinner" /> : '✓'}
                        </button>
                        <button
                          className="btn btn-reject btn-sm"
                          onClick={e => handleReject(e, r.id)}
                          disabled={actionLoading === r.id}
                          title="Reject — can be reversed later"
                        >
                          ✗
                        </button>
                      </div>
                    )}
                    {r.reviewed_by_username && (
                      <div className="text-muted" style={{ fontSize: '0.7rem', marginTop: 4 }}>
                        by {r.reviewed_by_username}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Sticky Bulk Action Bar */}
      {selectedIds.size > 0 && (
        <div className="bulk-action-bar">
          <div className="bulk-info">
            <span className="bulk-count">{selectedIds.size}</span>
            <span>record{selectedIds.size !== 1 ? 's' : ''} selected</span>
          </div>
          <div className="bulk-actions">
            <button
              className="btn btn-outline btn-sm"
              onClick={() => setSelectedIds(new Set())}
            >
              Clear Selection
            </button>
            <button
              className="btn btn-approve"
              onClick={handleBulkApprove}
              disabled={bulkLoading}
            >
              {bulkLoading
                ? <><span className="spinner" /> Approving...</>
                : `✓ Approve ${selectedIds.size} Record${selectedIds.size !== 1 ? 's' : ''}`
              }
            </button>
          </div>
        </div>
      )}
    </>
  );
}
