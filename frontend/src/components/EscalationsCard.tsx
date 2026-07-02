/**
 * EscalationsCard - Lead-scoped overdue items across the lead's changes.
 * Self-fetching; renders nothing when there is nothing overdue.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { changesApi } from '../api/changes';
import { t } from '../i18n/cmLabels';

export default function EscalationsCard() {
  const { data } = useQuery({
    queryKey: ['my-escalations'],
    queryFn: changesApi.myEscalations,
    refetchInterval: 60_000,
  });

  if (!data || data.length === 0) return null;

  return (
    <div className="bg-slate-800 rounded-lg border border-red-900/60 p-4">
      <h3 className="text-red-300 font-semibold mb-2">⚠ {t('esc.title')}</h3>
      <ul className="space-y-1">
        {data.map((e, i) => (
          <li key={`${e.kind}-${i}`} className="flex items-center gap-2 text-sm flex-wrap">
            <Link
              to={`/changes/${e.change_id}`}
              className="text-sky-400 hover:text-sky-300 font-medium"
            >
              {e.change_number}
            </Link>
            <span className="text-slate-300">{e.label}</span>
            <span className="text-slate-400">
              {e.owner_name ?? t('tasks.unclaimed')}
            </span>
            <span className="text-red-400 font-semibold">
              {e.days_overdue}d {t('tasks.overdue')}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
