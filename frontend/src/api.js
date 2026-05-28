/**
 * API client for the Breathe ESG backend.
 * Handles token auth, base URL, and provides typed fetch wrappers.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

// Token stored in memory for prototype. Production would use httpOnly cookies
// to prevent XSS. Documented in DECISIONS.md.
// Tradeoff: page refresh logs the user out — acceptable for a prototype.
let _token = null;
let _username = null;
let _tenantName = null;

function authHeaders() {
  return _token ? { Authorization: `Token ${_token}` } : {};
}

/**
 * Login — exchange username/password for a token.
 */
export async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.non_field_errors?.[0] || 'Invalid credentials');
  }
  const data = await res.json();
  _token = data.token;
  _username = username;

  // Fetch tenant info right after login
  try {
    const info = await fetchTenantInfo();
    _tenantName = info.tenant_name;
  } catch {
    _tenantName = null;
  }

  return data.token;
}

export function logout() {
  _token = null;
  _username = null;
  _tenantName = null;
}

export function isLoggedIn() {
  return !!_token;
}

export function getUsername() {
  return _username || 'user';
}

export function getTenantName() {
  return _tenantName || 'Unknown Tenant';
}

/**
 * Fetch current user's tenant info.
 */
export async function fetchTenantInfo() {
  const res = await fetch(`${API_BASE}/auth/me/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Tenant info failed: ${res.status}`);
  return res.json();
}

/**
 * Trigger SAP ingestion (dynamic generator or static file).
 */
export async function triggerSAP(fileParam = '') {
  const url = fileParam
    ? `${API_BASE}/ingest/sap/trigger/?file=${fileParam}`
    : `${API_BASE}/ingest/sap/trigger/`;
  const res = await fetch(url, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`SAP ingestion failed: ${res.status}`);
  return res.json();
}

/**
 * Upload a CSV file for utility or travel ingestion.
 */
export async function uploadCSV(endpoint, file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/ingest/${endpoint}/`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

/**
 * Fetch normalized records with optional filters.
 */
export async function fetchRecords(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, val]) => {
    if (val) params.set(key, val);
  });
  // Force the browser to bypass its cache and request fresh, real-time database results
  params.set('_t', Date.now());
  const url = `${API_BASE}/records/?${params.toString()}`;
  const res = await fetch(url, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Fetch records failed: ${res.status}`);
  return res.json();
}

/**
 * Approve a record.
 */
export async function approveRecord(id) {
  const res = await fetch(`${API_BASE}/records/${id}/approve/`, {
    method: 'PATCH',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `Approve failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Reject a record.
 */
export async function rejectRecord(id) {
  const res = await fetch(`${API_BASE}/records/${id}/reject/`, {
    method: 'PATCH',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `Reject failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Fetch recent ingestion batch history for the sidebar.
 */
export async function fetchBatches() {
  const res = await fetch(`${API_BASE}/batches/?_t=${Date.now()}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Fetch batches failed: ${res.status}`);
  return res.json();
}

/**
 * Bulk approve multiple records at once.
 * Only approves non-locked, non-rejected records belonging to the tenant.
 */
export async function bulkApprove(ids) {
  const res = await fetch(`${API_BASE}/records/bulk-approve/`, {
    method: 'PATCH',
    headers: {
      ...authHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `Bulk approve failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Download approved, locked records as an audit-ready CSV.
 *
 * Only approved+locked records are included. This is the set that would
 * go to an auditor, into a CDP submission, or a BRSR filing.
 * Pending, suspicious, and rejected records are excluded by design.
 */
export async function exportApprovedRecords() {
  const res = await fetch(`${API_BASE}/records/export/`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);

  // Pull tenant slug from Content-Disposition header if available,
  // otherwise fall back to a default filename.
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : 'emissions_inventory.csv';

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}
