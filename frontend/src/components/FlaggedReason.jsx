import { useState } from 'react';

/**
 * FlaggedReason — expandable text showing flagged_reason on suspicious rows.
 * Collapsed: shows first 60 chars with ⚠ icon.
 * Expanded: shows full text on click.
 */
export default function FlaggedReason({ reason }) {
  const [expanded, setExpanded] = useState(false);

  if (!reason) return null;

  return (
    <div
      className="flagged-reason"
      onClick={() => setExpanded(!expanded)}
      title={expanded ? 'Click to collapse' : 'Click to expand'}
    >
      <span className="flagged-icon">⚠</span>
      <span className="flagged-text">
        {expanded ? reason : `${reason.substring(0, 60)}${reason.length > 60 ? '...' : ''}`}
      </span>
      {reason.length > 60 && (
        <span className="flagged-toggle">
          {expanded ? '▲' : '▼'}
        </span>
      )}
    </div>
  );
}
