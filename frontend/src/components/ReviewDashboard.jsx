import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { fetchRecords, getUsername, getTenantName, exportApprovedRecords } from '../api';
import FilterBar from './FilterBar';
import RecordsTable from './RecordsTable';
import RecordDetailDrawer from './RecordDetailDrawer';
import FailedRowsPanel from './FailedRowsPanel';
import BatchHistory from './BatchHistory';

function computeStats(records) {
  const stats = {
    total: records.length,
    totalCO2: 0,
    scope1: 0, scope2: 0, scope3: 0,
    pending: 0, suspicious: 0, approved: 0, rejected: 0,
    bySrc: { sap: 0, utility: 0, travel: 0 },
  };
  records.forEach(r => {
    const co2 = parseFloat(r.co2e_kg) || 0;
    stats.totalCO2 += co2;
    if (r.scope === '1') stats.scope1 += co2;
    if (r.scope === '2') stats.scope2 += co2;
    if (r.scope === '3') stats.scope3 += co2;
    if (r.status === 'pending') stats.pending += 1;
    if (r.status === 'suspicious') stats.suspicious += 1;
    if (r.status === 'approved') stats.approved += 1;
    if (r.status === 'rejected') stats.rejected += 1;
    if (r.source_type) stats.bySrc[r.source_type] = (stats.bySrc[r.source_type] || 0) + 1;
  });
  return stats;
}

function computeGHGBreakdown(records) {
  const breakdown = {
    s1_stationary: { co2: 0, count: 0, suspicious: 0, pending: 0, approved: 0 },
    s1_mobile: { co2: 0, count: 0, suspicious: 0, pending: 0, approved: 0 },
    s2_electricity: { co2: 0, count: 0, suspicious: 0, pending: 0, approved: 0 },
    s3_flight: { co2: 0, count: 0, suspicious: 0, pending: 0, approved: 0 },
    s3_hotel: { co2: 0, count: 0, suspicious: 0, pending: 0, approved: 0 },
    s3_ground: { co2: 0, count: 0, suspicious: 0, pending: 0, approved: 0 },
  };

  records.forEach(r => {
    const co2 = parseFloat(r.co2e_kg) || 0;
    let target = null;

    if (r.source_type === 'sap') {
      target = breakdown.s1_stationary;
    } else if (r.source_type === 'utility') {
      target = breakdown.s2_electricity;
    } else if (r.source_type === 'travel') {
      if (r.scope === '1') {
        target = breakdown.s1_mobile;
      } else if (r.scope === '3') {
        const desc = (r.activity_description || '').toLowerCase();
        if (desc.startsWith('flight')) {
          target = breakdown.s3_flight;
        } else if (desc.startsWith('hotel')) {
          target = breakdown.s3_hotel;
        } else if (desc.startsWith('ground')) {
          target = breakdown.s3_ground;
        }
      }
    }

    if (target) {
      target.co2 += co2;
      target.count += 1;
      if (r.status === 'suspicious') target.suspicious += 1;
      if (r.status === 'pending') target.pending += 1;
      if (r.status === 'approved') target.approved += 1;
    }
  });

  return breakdown;
}

function formatTonnes(kg) {
  if (kg >= 1000) return `${(kg / 1000).toFixed(2)}t`;
  return `${kg.toFixed(1)} kg`;
}

export default function ReviewDashboard({ onLogout }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [records, setRecords] = useState([]);
  const [allRecords, setAllRecords] = useState([]);
  const [filters, setFilters] = useState({});
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [exporting, setExporting] = useState(false);

  // Failed rows passed via route state from IngestPage
  const [failedRows, setFailedRows] = useState([]);

  // Collect failed rows from route state on mount.
  // Deduplicate by source_type+batch_id so React StrictMode's double-invoke
  // of effects doesn't result in the same batch appearing twice.
  useEffect(() => {
    if (location.state?.failedRows?.length) {
      setFailedRows(prev => {
        const existingKeys = new Set(prev.map(b => `${b.source_type}-${b.batch_id}`));
        const incoming = location.state.failedRows.filter(
          b => !existingKeys.has(`${b.source_type}-${b.batch_id}`)
        );
        return incoming.length ? [...prev, ...incoming] : prev;
      });
      // Clear the route state so it doesn't re-add on back-navigation
      window.history.replaceState({}, document.title);
    }
  }, [location.state]);


  const loadRecords = useCallback(async (activeFilters = {}) => {
    setLoading(true);
    try {
      const data = await fetchRecords(activeFilters);
      const list = Array.isArray(data) ? data : data.results || [];
      setRecords(list);
      if (Object.keys(activeFilters).length === 0) {
        setAllRecords(list);
      }
    } catch (err) {
      console.error('Failed to load records:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRecords({}); }, [loadRecords]);
  useEffect(() => { loadRecords(filters); }, [filters, loadRecords]);

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  function showToast(message, type = 'success') {
    setToast({ message, type });
  }

  function handleRecordUpdate() {
    loadRecords(filters);
    fetchRecords({}).then(data => {
      const list = Array.isArray(data) ? data : data.results || [];
      setAllRecords(list);
    });
  }

  function handleFilterChange(newFilters) {
    setFilters(newFilters);
  }

  async function handleExport() {
    setExporting(true);
    try {
      await exportApprovedRecords();
      showToast(`Exported ${stats.approved} approved record${stats.approved !== 1 ? 's' : ''}`);
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setExporting(false);
    }
  }

  const stats = computeStats(allRecords);
  const ghgBreakdown = computeGHGBreakdown(allRecords);

  const reviewProgress = stats.total > 0
    ? Math.round((stats.approved / stats.total) * 100)
    : 0;

  const totalFailedRows = failedRows.reduce(
    (sum, b) => sum + (b.rows?.length || 0), 0
  );

  function renderTreeStatus(cat) {
    if (cat.suspicious > 0) {
      return <span className="tree-badge tree-badge-suspicious">⚠ {cat.suspicious} suspicious</span>;
    }
    if (cat.pending > 0) {
      return <span className="tree-badge tree-badge-pending">{cat.pending} pending</span>;
    }
    return <span className="tree-badge tree-badge-reviewed">✓ reviewed</span>;
  }

  function renderGHGTree(b) {
    const hasS1 = b.s1_stationary.count > 0 || b.s1_mobile.count > 0;
    const hasS2 = b.s2_electricity.count > 0;
    const hasS3 = b.s3_flight.count > 0 || b.s3_hotel.count > 0 || b.s3_ground.count > 0;

    if (!hasS1 && !hasS2 && !hasS3) {
      return (
        <div className="tree-empty-state">
          <p>No active GHG protocol categories. Ingest data to build this inventory dynamically.</p>
        </div>
      );
    }

    return (
      <div className="ghg-tree-root">
        {/* Scope 1 */}
        {hasS1 && (
          <div className="ghg-scope-section s1-border">
            <div className="ghg-scope-header">
              <span className="ghg-scope-indicator s1-bg" />
              <div className="ghg-scope-info">
                <h4>Scope 1 — Direct Emissions</h4>
                <span className="scope-total-co2">{formatTonnes(b.s1_stationary.co2 + b.s1_mobile.co2)}</span>
              </div>
            </div>
            <div className="ghg-scope-children">
              {b.s1_stationary.count > 0 && (
                <div className="ghg-category-node">
                  <div className="ghg-node-header">
                    <span className="ghg-node-title">Stationary Combustion</span>
                    <span className="ghg-node-co2">{formatTonnes(b.s1_stationary.co2)}</span>
                  </div>
                  <div className="ghg-node-details">
                    <span className="ghg-node-desc">SAP fuel purchase ({b.s1_stationary.count} POs)</span>
                    {renderTreeStatus(b.s1_stationary)}
                  </div>
                </div>
              )}
              {b.s1_mobile.count > 0 && (
                <div className="ghg-category-node">
                  <div className="ghg-node-header">
                    <span className="ghg-node-title">Mobile Combustion</span>
                    <span className="ghg-node-co2">{formatTonnes(b.s1_mobile.co2)}</span>
                  </div>
                  <div className="ghg-node-details">
                    <span className="ghg-node-desc">Company vehicles ({b.s1_mobile.count} trips)</span>
                    {renderTreeStatus(b.s1_mobile)}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Scope 2 */}
        {hasS2 && (
          <div className="ghg-scope-section s2-border">
            <div className="ghg-scope-header">
              <span className="ghg-scope-indicator s2-bg" />
              <div className="ghg-scope-info">
                <h4>Scope 2 — Indirect Emissions</h4>
                <span className="scope-total-co2">{formatTonnes(b.s2_electricity.co2)}</span>
              </div>
            </div>
            <div className="ghg-scope-children">
              <div className="ghg-category-node">
                <div className="ghg-node-header">
                  <span className="ghg-node-title">Purchased Electricity</span>
                  <span className="ghg-node-co2">{formatTonnes(b.s2_electricity.co2)}</span>
                </div>
                <div className="ghg-node-details">
                  <span className="ghg-node-desc">Grid utility consumption ({b.s2_electricity.count} bills)</span>
                  {renderTreeStatus(b.s2_electricity)}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Scope 3 */}
        {hasS3 && (
          <div className="ghg-scope-section s3-border">
            <div className="ghg-scope-header">
              <span className="ghg-scope-indicator s3-bg" />
              <div className="ghg-scope-info">
                <h4>Scope 3 — Value Chain</h4>
                <span className="scope-total-co2">{formatTonnes(b.s3_flight.co2 + b.s3_hotel.co2 + b.s3_ground.co2)}</span>
              </div>
            </div>
            <div className="ghg-scope-children">
              <div className="ghg-category-node">
                <div className="ghg-node-header">
                  <span className="ghg-node-title">Category 6: Business Travel</span>
                  <span className="ghg-node-co2">{formatTonnes(b.s3_flight.co2 + b.s3_hotel.co2 + b.s3_ground.co2)}</span>
                </div>
                <div className="ghg-node-details" style={{ marginBottom: 8 }}>
                  <span className="ghg-node-desc">Corporate travel program alignment</span>
                </div>
                
                <div className="ghg-subcategory-list">
                  {b.s3_flight.count > 0 && (
                    <div className="ghg-subnode">
                      <div className="ghg-subnode-row">
                        <span className="ghg-subnode-title">✈ Flights</span>
                        <span className="ghg-subnode-co2">{formatTonnes(b.s3_flight.co2)}</span>
                      </div>
                      <div className="ghg-subnode-meta">
                        <span className="ghg-subnode-count">({b.s3_flight.count} segments)</span>
                        {renderTreeStatus(b.s3_flight)}
                      </div>
                    </div>
                  )}
                  {b.s3_hotel.count > 0 && (
                    <div className="ghg-subnode">
                      <div className="ghg-subnode-row">
                        <span className="ghg-subnode-title">🏨 Hotels</span>
                        <span className="ghg-subnode-co2">{formatTonnes(b.s3_hotel.co2)}</span>
                      </div>
                      <div className="ghg-subnode-meta">
                        <span className="ghg-subnode-count">({b.s3_hotel.count} bookings)</span>
                        {renderTreeStatus(b.s3_hotel)}
                      </div>
                    </div>
                  )}
                  {b.s3_ground.count > 0 && (
                    <div className="ghg-subnode">
                      <div className="ghg-subnode-row">
                        <span className="ghg-subnode-title">🚗 Ground (third-party)</span>
                        <span className="ghg-subnode-co2">{formatTonnes(b.s3_ground.co2)}</span>
                      </div>
                      <div className="ghg-subnode-meta">
                        <span className="ghg-subnode-count">({b.s3_ground.count} trips)</span>
                        {renderTreeStatus(b.s3_ground)}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-left">
          <button className="back-btn" onClick={() => navigate('/')}>
            ← Ingestion
          </button>
          <div className="logo">
            <span className="leaf">🌿</span>
            <span>Breathe ESG</span>
          </div>
        </div>
        <div className="header-right">
          <div className="tenant-badge">{getTenantName()}</div>
          <div className="user-info">
            <span>👤 {getUsername()}</span>
            <button className="logout-btn" onClick={onLogout}>Sign out</button>
          </div>
        </div>
      </header>

      <main className="review-page">
        {/* Toast */}
        {toast && (
          <div className={`toast toast-${toast.type}`}>
            {toast.type === 'success' ? '✅' : '❌'} {toast.message}
          </div>
        )}

        <div className="page-intro">
          <h1>Review Dashboard</h1>
          <p>
            Normalized emission records from all ingested sources. Review what
            came in, investigate suspicious entries, and approve records for
            audit lock. Click any row for the full audit trail.
          </p>
        </div>

        {/* ── Failed Rows Panel (if any) ── */}
        <FailedRowsPanel failedRows={failedRows} />

        {/* ── Summary Cards ── */}
        <div className="summary-strip">
          <div className="summary-card">
            <div className="summary-label">Total Records</div>
            <div className="summary-value">{stats.total}</div>
            <div className="summary-breakdown">
              <span className="chip chip-sap">{stats.bySrc.sap || 0} SAP</span>
              <span className="chip chip-utility">{stats.bySrc.utility || 0} Utility</span>
              <span className="chip chip-travel">{stats.bySrc.travel || 0} Travel</span>
            </div>
          </div>

          <div className="summary-card">
            <div className="summary-label">Total CO₂e</div>
            <div className="summary-value accent">{formatTonnes(stats.totalCO2)}</div>
            <div className="summary-breakdown">
              <span title="Scope 1 — Direct fuel">S1: {formatTonnes(stats.scope1)}</span>
              <span title="Scope 2 — Electricity">S2: {formatTonnes(stats.scope2)}</span>
              <span title="Scope 3 — Travel">S3: {formatTonnes(stats.scope3)}</span>
            </div>
          </div>

          <div className="summary-card warn">
            <div className="summary-label">⚠ Suspicious</div>
            <div className="summary-value">{stats.suspicious}</div>
            <div className="summary-sub">
              Flagged by quality checks — needs analyst review
            </div>
          </div>

          {totalFailedRows > 0 && (
            <div className="summary-card error-card">
              <div className="summary-label">🚫 Rejected at Ingestion</div>
              <div className="summary-value rejected-val">{totalFailedRows}</div>
              <div className="summary-sub">
                Failed validation — not imported
              </div>
            </div>
          )}

          <div className="summary-card">
            <div className="summary-label">Awaiting Review</div>
            <div className="summary-value pending-val">{stats.pending}</div>
            <div className="summary-sub">
              Pending records not yet approved or rejected
            </div>
          </div>

          <div className="summary-card">
            <div className="summary-label">Approved & Locked 🔒</div>
            <div className="summary-value approved-val">{stats.approved}</div>
            <div className="review-progress">
              <div className="review-progress-bar" style={{ width: `${reviewProgress}%` }} />
            </div>
            <div className="summary-sub">{reviewProgress}% of records reviewed</div>
          </div>
        </div>

        {/* ── 2-Column Dashboard Grid ── */}
        <div className="dashboard-grid">
          {/* Main Content (Records Table) */}
          <div className="main-content">
            <div className="records-section">
              <div className="section-header section-header-row">
                <div>
                  <h2>
                    📋 Emission Records
                    <span className="records-count">({records.length} shown)</span>
                  </h2>
                  <p className="section-desc">
                    Click any row for full audit details. Use checkboxes for bulk actions.
                    Suspicious records are flagged with expandable warnings.
                  </p>
                </div>
                <button
                  className="btn btn-export btn-sm"
                  onClick={handleExport}
                  disabled={exporting || stats.approved === 0}
                  title={stats.approved === 0 ? 'No approved records to export' : `Export ${stats.approved} approved record${stats.approved !== 1 ? 's' : ''} as CSV`}
                >
                  {exporting
                    ? <><span className="spinner" /> Generating...</>
                    : <>📥 Export Approved ({stats.approved})</>
                  }
                </button>
              </div>

              <FilterBar filters={filters} onChange={handleFilterChange} />

              {loading ? (
                <div className="empty-state">
                  <span className="spinner" style={{ width: 32, height: 32 }} />
                  <p>Loading records...</p>
                </div>
              ) : allRecords.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-icon">📭</div>
                  <h3>No records found</h3>
                  <p>This tenant has no ingested data yet.</p>
                  <button className="btn btn-primary" onClick={() => navigate('/')}>
                    ← Go to Ingestion
                  </button>
                </div>
              ) : (
                <RecordsTable
                  records={records}
                  onUpdate={handleRecordUpdate}
                  showToast={showToast}
                  onRowClick={setSelectedRecord}
                />
              )}
            </div>
          </div>

          {/* Sidebar */}
          <aside className="sidebar">
            {/* GHG Protocol Alignment Card */}
            <div className="sidebar-card">
              <div className="sidebar-card-header">
                <h3>GHG Inventory Alignment</h3>
                <p className="sidebar-desc">Active Protocol Categories covered by your data</p>
              </div>
              <div className="ghg-tree">
                {renderGHGTree(ghgBreakdown)}
              </div>
            </div>

            {/* Batch History Card */}
            <BatchHistory />
          </aside>
        </div>
      </main>

      {/* Detail Drawer */}
      <RecordDetailDrawer
        record={selectedRecord}
        onClose={() => setSelectedRecord(null)}
        onUpdate={handleRecordUpdate}
        showToast={showToast}
      />
    </div>
  );
}
