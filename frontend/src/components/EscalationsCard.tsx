/**
 * EscalationsCard - Lead-scoped overdue items across the lead's changes.
 * Self-fetching; renders nothing when there is nothing overdue.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { formatCalendarDate } from '../lib/format';
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
            {e.kind === 'deadline' ? (
              <span className={e.state === 'overdue' ? 'text-red-400 font-semibold' : 'text-amber-300 font-semibold'}>
                {/* A6-08: which deadline (quote or release), then its state */}
                {e.deadline_kind
                  ? `${t(e.deadline_kind === 'release' ? 'esc.releaseDue' : 'esc.quoteDue')
                    .replace('{d}', formatCalendarDate(e.required_by_date))} · `
                  : ''}
                {e.state === 'overdue'
                  ? t('deadline.overdue')
                  : e.deadline_kind ? t('esc.atRisk')
                    : `${t('esc.atRisk')} · due ${formatCalendarDate(e.required_by_date)}`}
              </span>
            ) : (
              <>
                <span className="text-slate-300">{e.label}</span>
                {/* Tasks are mandatory per department — no claim step, so a
                    missing owner is not a state worth announcing. */}
                {e.owner_name && (
                  <span className="text-slate-400">{e.owner_name}</span>
                )}
                <span className="text-red-400 font-semibold">
                  {e.days_overdue}d {t('tasks.overdue')}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
