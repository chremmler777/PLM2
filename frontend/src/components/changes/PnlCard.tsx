import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { t } from '../../i18n/cmLabels';
import type { ChangeDetail, ChangeStatus, PnlActuals } from '../../types/change';

const HIDDEN_STATUSES: ChangeStatus[] = ['captured', 'scoping', 'in_assessment'];

const fmtMoney = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : v.toLocaleString('de-DE');

function marginAccent(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'text-slate-400';
  return v >= 0 ? 'text-emerald-400' : 'text-red-400';
}

/**
 * Compact per-change P&L card for the commercial cockpit tab. Semantics
 * mirror PnlPage/Task 1: customer-relevant changes show a quoted-price
 * "Revenue" figure and a real "Margin"; internal changes show the
 * PM-approved budget snapshot and label the delta "vs. approved budget"
 * (never "profit"). Hidden entirely before costing (captured, scoping,
 * in_assessment) since there's no meaningful cost data yet.
 */
const hoursText = (n: number) => String(Math.round(n * 100) / 100);

/** A named extra reads as a name; an unknown key still reads as itself. */
const extraLabel = (key: string, given?: string | null): string => {
  if (given) return given;
  const label = t(`actuals.extra.${key}`);
  return label === `actuals.extra.${key}` ? key : label;
};

/**
 * What the change actually cost, once there is such a thing. Additive by
 * design: the plan figures above are the same with or without this block, and a
 * payload from a backend that does not send `actuals` renders exactly as before.
 *
 * Hours that could not be priced are called out rather than silently counted as
 * zero — a total built on a missing rate is a floor, and saying so is cheaper
 * than having somebody discover it in a review.
 */
function ActualsSection({
  actuals, departmentName,
}: {
  actuals: PnlActuals;
  departmentName: (id: number) => string;
}) {
  const rows = actuals.by_department ?? [];
  const extras = actuals.extras ?? [];
  const anyUnrated = actuals.unrated ?? rows.some((r) => r.unrated);
  const total = actuals.total_cost ?? (actuals.internal_cost + (actuals.extra_cost ?? 0));

  return (
    <div data-testid="pnl-actuals" className="border-t border-slate-700 mt-4 pt-3 md:col-span-3">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="text-xs text-slate-400 uppercase tracking-wide">
          {t('actuals.title')}
        </span>
        <span className="text-xs text-slate-500">{t('actuals.intro')}</span>
      </div>

      {rows.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {rows.map((r) => (
            <li key={r.department_id} data-testid={`pnl-actual-dept-${r.department_id}`}
              className="flex items-baseline gap-2 text-xs text-slate-300">
              <span className="min-w-0 flex-1 text-slate-200">
                {departmentName(r.department_id)}
              </span>
              <span className="tabular-nums text-slate-400">{hoursText(r.hours)} h</span>
              {r.unrated && (
                <span data-testid={`pnl-actual-unrated-${r.department_id}`}
                  className="rounded bg-amber-900/70 text-amber-200 px-1.5 py-0 text-[10px] leading-tight">
                  {t('actuals.unrated')}
                </span>
              )}
              <span className="tabular-nums text-slate-100 w-24 text-right">
                {fmtMoney(r.internal_cost)}
              </span>
              <span className="tabular-nums text-slate-500 w-24 text-right">
                {t('actuals.plan')} {fmtMoney(r.plan_internal_cost)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {anyUnrated && (
        <p data-testid="pnl-actuals-unrated" className="mt-1 text-[11px] text-amber-300">
          {t('actuals.unratedHint')}
        </p>
      )}

      {extras.length > 0 && (
        <div className="mt-2">
          <span className="text-xs text-slate-400">{t('actuals.extras')}</span>
          <ul className="mt-0.5 space-y-0.5">
            {extras.map((x) => (
              <li key={x.key} data-testid={`pnl-actual-extra-${x.key}`}
                className="flex items-baseline gap-2 text-xs text-slate-300">
                <span className="min-w-0 flex-1">{extraLabel(x.key, x.label)}</span>
                <span className="tabular-nums text-slate-100">{fmtMoney(x.amount)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-2 flex items-baseline gap-3 flex-wrap text-sm">
        <span className="text-slate-400 text-xs uppercase tracking-wide">
          {t('actuals.total')}
        </span>
        <span data-testid="pnl-actuals-total" className="font-semibold text-slate-100 tabular-nums">
          {fmtMoney(total)}
        </span>
        {actuals.plan_internal_cost !== null && actuals.plan_internal_cost !== undefined && (
          <span className="text-xs text-slate-500 tabular-nums">
            {t('actuals.plan')} {fmtMoney(actuals.plan_internal_cost)}
          </span>
        )}
        {actuals.delta !== null && actuals.delta !== undefined && (
          <span data-testid="pnl-actuals-delta"
            className={`text-xs font-medium tabular-nums ${
              actuals.delta > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
            {t('actuals.delta')} {actuals.delta > 0 ? '+' : ''}{fmtMoney(actuals.delta)}
          </span>
        )}
      </div>
    </div>
  );
}

export default function PnlCard({ change, departments = [] }: {
  change: ChangeDetail;
  /** Only used to name the actual-cost rows; absent is a legible fallback. */
  departments?: { id: number; name: string }[];
}) {
  const hidden = HIDDEN_STATUSES.includes(change.status);

  const { data } = useQuery({
    queryKey: ['change-summation', change.id],
    queryFn: () => changesApi.getSummation(change.id),
    enabled: !hidden,
  });

  if (hidden) return null;

  const totals = data?.totals;
  const internalCost = totals ? totals.one_time_internal + totals.lifecycle_internal : undefined;
  const externalCost = totals ? totals.one_time_external + totals.lifecycle_external : undefined;
  const totalCost = totals?.grand_total;

  const revenue = change.customer_relevant ? change.quoted_price : change.internal_approved_amount;
  const margin = revenue !== null && revenue !== undefined && totalCost !== undefined
    ? revenue - totalCost
    : undefined;
  const marginLabel = change.customer_relevant ? 'Margin' : 'vs. approved budget';

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 mb-4 grid grid-cols-1 md:grid-cols-3 gap-4">
      <div>
        <div className="text-xs text-slate-400 uppercase tracking-wide">
          {change.customer_relevant ? 'Revenue' : 'Approved budget'}
        </div>
        <div className="text-xl font-semibold text-slate-100 mt-1">{fmtMoney(revenue)}</div>
      </div>

      <div>
        <div className="text-xs text-slate-400 uppercase tracking-wide">Cost</div>
        <div className="text-xl font-semibold text-slate-100 mt-1">{fmtMoney(totalCost)}</div>
        <div className="text-xs text-slate-500 mt-1">
          Int. {fmtMoney(internalCost)} · Ext. {fmtMoney(externalCost)}
        </div>
      </div>

      <div>
        <div className="text-xs text-slate-400 uppercase tracking-wide">{marginLabel}</div>
        <div className={`text-xl font-semibold mt-1 ${marginAccent(margin)}`}>{fmtMoney(margin)}</div>
      </div>

      {data?.actuals && (
        <ActualsSection actuals={data.actuals}
          departmentName={(id) => departments.find((d) => d.id === id)?.name ?? `#${id}`} />
      )}
    </div>
  );
}
