/**
 * StatusBadge - Display status with color coding
 */

interface Props {
  status: string;
  variant?: 'primary' | 'success' | 'warning' | 'error' | 'default';
}

const variants = {
  primary: 'bg-blue-100 text-blue-800',
  success: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
  error: 'bg-red-100 text-red-800',
  default: 'bg-gray-100 text-gray-800',
};

export default function StatusBadge({ status, variant = 'default' }: Props) {
  return (
    <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold ${variants[variant]}`}>
      {status}
    </span>
  );
}
