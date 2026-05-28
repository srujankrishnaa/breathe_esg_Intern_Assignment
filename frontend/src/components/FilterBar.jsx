export default function FilterBar({ filters, onChange }) {
  function update(key, value) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <div className="filter-bar">
      <div className="filter-group">
        <label htmlFor="filter-source">Source</label>
        <select
          id="filter-source"
          value={filters.source_type || ''}
          onChange={e => update('source_type', e.target.value)}
        >
          <option value="">All Sources</option>
          <option value="sap">SAP</option>
          <option value="utility">Utility</option>
          <option value="travel">Travel</option>
        </select>
      </div>

      <div className="filter-group">
        <label htmlFor="filter-scope">Scope</label>
        <select
          id="filter-scope"
          value={filters.scope || ''}
          onChange={e => update('scope', e.target.value)}
        >
          <option value="">All Scopes</option>
          <option value="1">Scope 1</option>
          <option value="2">Scope 2</option>
          <option value="3">Scope 3</option>
        </select>
      </div>

      <div className="filter-group">
        <label htmlFor="filter-status">Status</label>
        <select
          id="filter-status"
          value={filters.status || ''}
          onChange={e => update('status', e.target.value)}
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="suspicious">Suspicious</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      <div className="filter-group">
        <label htmlFor="filter-from">From</label>
        <input
          id="filter-from"
          type="date"
          value={filters.date_from || ''}
          onChange={e => update('date_from', e.target.value)}
        />
      </div>

      <div className="filter-group">
        <label htmlFor="filter-to">To</label>
        <input
          id="filter-to"
          type="date"
          value={filters.date_to || ''}
          onChange={e => update('date_to', e.target.value)}
        />
      </div>

      <div className="filter-group" style={{ alignSelf: 'flex-end' }}>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => onChange({})}
        >
          Clear
        </button>
      </div>
    </div>
  );
}
