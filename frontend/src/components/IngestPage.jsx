import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { triggerSAP, uploadCSV, getUsername, getTenantName } from '../api';

const SAP_STATIC_FILES = [
  { value: '', label: 'Generate fresh data' },
  { value: 'sap_unknown_plant', label: 'Test: Unknown plant codes' },
  { value: 'sap_high_quantity', label: 'Test: High quantity (suspicious)' },
];

export default function IngestPage({ onLogout }) {
  const navigate = useNavigate();

  // SAP state
  const [sapMode, setSapMode] = useState('');
  const [sapLoading, setSapLoading] = useState(false);
  const [sapResult, setSapResult] = useState(null);

  // Utility state
  const [utilFile, setUtilFile] = useState(null);
  const [utilLoading, setUtilLoading] = useState(false);
  const [utilResult, setUtilResult] = useState(null);

  // Travel state
  const [travelFile, setTravelFile] = useState(null);
  const [travelLoading, setTravelLoading] = useState(false);
  const [travelResult, setTravelResult] = useState(null);

  // Track which sources have been ingested
  const [ingested, setIngested] = useState({ sap: false, utility: false, travel: false });

  // Collect failed rows from ingestion responses to pass to Review Dashboard
  const [failedRows, setFailedRows] = useState([]);

  async function handleSAP() {
    setSapLoading(true);
    setSapResult(null);
    try {
      const data = await triggerSAP(sapMode);
      setSapResult({ success: true, data });
      setIngested(prev => ({ ...prev, sap: true }));
      // Collect failed rows if any
      if (data.failed_rows && data.failed_rows.length > 0) {
        setFailedRows(prev => [...prev, { source_type: 'sap', batch_id: data.batch_id, rows: data.failed_rows }]);
      }
    } catch (err) {
      setSapResult({ success: false, error: err.message });
    } finally {
      setSapLoading(false);
    }
  }

  async function handleUtility() {
    if (!utilFile) return;
    setUtilLoading(true);
    setUtilResult(null);
    try {
      const data = await uploadCSV('utility', utilFile);
      setUtilResult({ success: true, data });
      setUtilFile(null);
      setIngested(prev => ({ ...prev, utility: true }));
      if (data.failed_rows && data.failed_rows.length > 0) {
        setFailedRows(prev => [...prev, { source_type: 'utility', batch_id: data.batch_id, rows: data.failed_rows }]);
      }
    } catch (err) {
      setUtilResult({ success: false, error: err.message });
    } finally {
      setUtilLoading(false);
    }
  }

  async function handleTravel() {
    if (!travelFile) return;
    setTravelLoading(true);
    setTravelResult(null);
    try {
      const data = await uploadCSV('travel', travelFile);
      setTravelResult({ success: true, data });
      setTravelFile(null);
      setIngested(prev => ({ ...prev, travel: true }));
      if (data.failed_rows && data.failed_rows.length > 0) {
        setFailedRows(prev => [...prev, { source_type: 'travel', batch_id: data.batch_id, rows: data.failed_rows }]);
      }
    } catch (err) {
      setTravelResult({ success: false, error: err.message });
    } finally {
      setTravelLoading(false);
    }
  }

  const anyIngested = ingested.sap || ingested.utility || ingested.travel;

  function renderResult(result) {
    if (!result) return null;
    if (!result.success) {
      return <div className="ingest-feedback error">❌ {result.error}</div>;
    }
    const d = result.data;
    return (
      <div className="ingest-feedback success">
        <div className="feedback-header">✅ Batch #{d.batch_id} processed</div>
        <div className="feedback-stats">
          <span>{d.total} rows total</span>
          {d.suspicious > 0 && <span className="stat-warn">⚠ {d.suspicious} suspicious</span>}
          {d.failed > 0 && <span className="stat-error">✗ {d.failed} failed</span>}
          {d.duplicates_skipped > 0 && <span className="stat-info">↻ {d.duplicates_skipped} duplicates skipped</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="logo">
          <span className="leaf">🌿</span>
          <span>Breathe ESG</span>
        </div>
        <div className="header-right">
          <div className="tenant-badge">{getTenantName()}</div>
          <div className="user-info">
            <span>👤 {getUsername()}</span>
            <button className="logout-btn" onClick={onLogout}>Sign out</button>
          </div>
        </div>
      </header>

      <main className="ingest-page">
        <div className="page-intro">
          <h1>Data Ingestion</h1>
          <p>
            Import emission records from your data sources. Once you've uploaded data
            from at least one source, proceed to the review dashboard to normalize,
            audit, and approve records.
          </p>
        </div>

        {/* ── 3 Source Cards ── */}
        <div className="source-grid">

          {/* SAP */}
          <div className={`source-card ${ingested.sap ? 'completed' : ''}`}>
            <div className="source-card-header">
              <div className="source-icon-wrap sap">⛽</div>
              <div>
                <h3>SAP — Fuel Procurement</h3>
                <span className="scope-chip scope1">Scope 1</span>
              </div>
              {ingested.sap && <span className="check-mark">✓</span>}
            </div>
            <p className="source-card-desc">
              Simulate an SAP OData feed or load a static test file.
              Each trigger generates purchase order records for fuel
              combustion at your registered plants.
            </p>
            <div className="source-card-actions">
              <select
                className="sap-select"
                value={sapMode}
                onChange={e => setSapMode(e.target.value)}
              >
                {SAP_STATIC_FILES.map(f => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
              <button
                className="btn btn-primary"
                onClick={handleSAP}
                disabled={sapLoading}
              >
                {sapLoading
                  ? <><span className="spinner" /> Processing...</>
                  : '⚡ Trigger Ingestion'}
              </button>
            </div>
            {renderResult(sapResult)}
          </div>

          {/* Utility */}
          <div className={`source-card ${ingested.utility ? 'completed' : ''}`}>
            <div className="source-card-header">
              <div className="source-icon-wrap utility">💡</div>
              <div>
                <h3>Utility — Electricity</h3>
                <span className="scope-chip scope2">Scope 2</span>
              </div>
              {ingested.utility && <span className="check-mark">✓</span>}
            </div>
            <p className="source-card-desc">
              Upload a CSV export from your utility portal (BESCOM, MSEDCL, TGSPDCL).
              Records will be normalized to kWh and converted to CO₂e using
              regional emission factors.
            </p>
            <div className="source-card-actions">
              <div className="file-upload-row">
                <label
                  htmlFor="util-file-input"
                  className={`file-label ${utilFile ? 'has-file' : ''}`}
                >
                  {utilFile ? utilFile.name : '📎 Choose CSV file...'}
                </label>
                <input
                  id="util-file-input"
                  type="file"
                  style={{ display: 'none' }}
                  accept=".csv"
                  onChange={e => setUtilFile(e.target.files[0])}
                />
              </div>
              <button
                className="btn btn-primary"
                onClick={handleUtility}
                disabled={!utilFile || utilLoading}
              >
                {utilLoading ? <><span className="spinner" /> Uploading...</> : '⬆ Upload'}
              </button>
            </div>
            {renderResult(utilResult)}
          </div>

          {/* Travel */}
          <div className={`source-card ${ingested.travel ? 'completed' : ''}`}>
            <div className="source-card-header">
              <div className="source-icon-wrap travel">✈️</div>
              <div>
                <h3>Travel — Corporate Travel</h3>
                <span className="scope-chip scope3">Scope 3</span>
              </div>
              {ingested.travel && <span className="check-mark">✓</span>}
            </div>
            <p className="source-card-desc">
              Upload a CSV from your Concur or Navan export. Supports flights,
              hotel stays, and ground transport. Converted to CO₂e based on
              distance, cabin class, and transport type.
            </p>
            <div className="source-card-actions">
              <div className="file-upload-row">
                <label
                  htmlFor="travel-file-input"
                  className={`file-label ${travelFile ? 'has-file' : ''}`}
                >
                  {travelFile ? travelFile.name : '📎 Choose CSV file...'}
                </label>
                <input
                  id="travel-file-input"
                  type="file"
                  style={{ display: 'none' }}
                  accept=".csv"
                  onChange={e => setTravelFile(e.target.files[0])}
                />
              </div>
              <button
                className="btn btn-primary"
                onClick={handleTravel}
                disabled={!travelFile || travelLoading}
              >
                {travelLoading ? <><span className="spinner" /> Uploading...</> : '⬆ Upload'}
              </button>
            </div>
            {renderResult(travelResult)}
          </div>
        </div>

        {/* ── CTA ── */}
        <div className={`review-cta ${anyIngested ? 'visible' : ''}`}>
          <div className="cta-content">
            <div className="cta-check-list">
              <span className={ingested.sap ? 'done' : ''}>
                {ingested.sap ? '✅' : '⬜'} SAP
              </span>
              <span className={ingested.utility ? 'done' : ''}>
                {ingested.utility ? '✅' : '⬜'} Utility
              </span>
              <span className={ingested.travel ? 'done' : ''}>
                {ingested.travel ? '✅' : '⬜'} Travel
              </span>
            </div>
            <button
              className="btn btn-cta"
              onClick={() => navigate('/review', { state: { failedRows } })}
            >
              Open Review Dashboard →
            </button>
          </div>
        </div>

        {/* Always show link to review for returning users */}
        {!anyIngested && (
          <div className="review-link-quiet">
            <button
              className="btn btn-outline"
              onClick={() => navigate('/review')}
            >
              Go to Review Dashboard →
            </button>
            <span className="review-link-hint">Already ingested data? Go straight to review.</span>
          </div>
        )}
      </main>
    </div>
  );
}
