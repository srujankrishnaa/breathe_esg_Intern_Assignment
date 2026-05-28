/**
 * StatusBadge — renders review status as a colored pill.
 * pending=amber, suspicious=orange, approved=green, rejected=red.
 */

const STATUS_CLASSES = {
  pending: 'badge-pending',
  approved: 'badge-approved',
  rejected: 'badge-rejected',
  suspicious: 'badge-suspicious',
};

export default function StatusBadge({ status }) {
  return (
    <span className={`badge ${STATUS_CLASSES[status] || ''}`}>
      {status}
    </span>
  );
}
