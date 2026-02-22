/**
 * StatusBadge - Display status with color coding
 */

interface Props {
  status: string;
  variant?: 'primary' | 'success' | 'warning' | 'error' | 'default';
}

const variants = {
  primary: 'bg-blue-900 text-blue-100',
  success: 'bg-green-900 text-green-100',
  warning: 'bg-yellow-900 text-yellow-100',
  error: 'bg-red-900 text-red-100',
  default: 'bg-slate-700 text-slate-100',
};

export default function StatusBadge({ status, variant = 'default' }: Props) {
  return (
    <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold ${variants[variant]}`}>
      {status}
    </span>
  );
}
