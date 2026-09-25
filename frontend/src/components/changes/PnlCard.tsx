import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { t } from '../../i18n/cmLabels';
import type { ChangeDetail, ChangeStatus, PnlActualExtra, PnlActuals } from '../../types/change';

const HIDDEN_STATUSES: ChangeStatus[] = ['captured', 'scoping', 'in_assessment'];
/** Stages where booked hours exist, so an actuals block is expected. */
const ACTUALS_STATUSES: ChangeStatus[] = ['in_implementation', 'in_validation', 'released', 'closed'];

const moneyFmt = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** "13.629,50": always two decimals, de-DE grouping. */
const fmtMoney = (v: number | null | undefined) =>
  v === null || v === undefined || !Number.isFinite(v) ? '-' : moneyFmt.format(v);

function marginAccent(v: number | null | undefined): string {
  if (v === null || v === undefined || Math.abs(v) < 0.005) return 'text-slate-400';
  return v > 0 ? 'text-emerald-400' : 'text-red-400';
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
/** A finite number, or null: NaN and missing fields never reach the card. */
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null

interface NormalRow {
  department_id: number
  department_name?: string | null
  hours: number
  internal_cost: number
  unrated: boolean
  plan: number | null
}

/**
 * The backend serves the actuals block as `departments / actual_cost /
 * booked_hours / total_actual / total_plan / variance` (ActualsBlock); older
 * payloads and fixtures use `by_department / internal_cost / hours /
 * total_cost / delta`. Both read the same here, and a field that is absent
 * stays absent instead of turning the total into NaN.
 */
function normalizeActuals(raw: PnlActuals | Record<string, unknown>) {
  const a = raw as Record<string, unknown>
  const rawRows = (Array.isArray(a.by_department) ? a.by_department
    : Array.isArray(a.departments) ? a.departments : []) as Record<string, unknown>[]
  const rows: NormalRow[] = rawRows.map((r) => ({
    department_id: Number(r.department_id),
    department_name: (r.department_name as string | null | undefined) ?? null,
    hours: num(r.hours) ?? num(r.booked_hours) ?? 0,
    internal_cost: num(r.internal_cost) ?? num(r.actual_cost) ?? 0,
    unrated: !!r.unrated,
    plan: num(r.plan_internal_cost) ?? num(r.plan_cost),
  }))
  const extras = ((Array.isArray(a.extras) ? a.extras : []) as PnlActualExtra[])
  const extraSum = extras.reduce((s, x) => s + (num(x.amount) ?? 0), 0)
  const internal = num(a.internal_cost) ?? num(a.total_actual)
    ?? rows.reduce((s, r) => s + r.internal_cost, 0)
  const extraCost = num(a.extra_cost) ?? num(a.total_extras) ?? extraSum
  const total = num(a.total_cost) ?? internal + extraCost
  const plan = num(a.plan_internal_cost) ?? num(a.total_plan)
  // Actual minus plan, on the same total the card shows (extras included):
  // the backend's variance leaves the extras out.
  const delta = plan !== null ? total - plan : num(a.delta) ?? num(a.variance)
  const unrated = typeof a.unrated === 'boolean' ? a.unrated
    : typeof a.unrated_hours === 'boolean' ? a.unrated_hours
    : rows.some((r) => r.unrated)
  const hasData = rows.some((r) => r.hours > 0 || r.internal_cost !== 0)
    || extras.some((x) => num(x.amount) !== null)
  return { rows, extras, total, plan, delta, unrated, hasData }
}

function ActualsSection({
  actuals, departmentName,
}: {
  actuals: ReturnType<typeof normalizeActuals>;
  departmentName: (id: number, given?: string | null) => string;
}) {
  const { rows, extras, total } = actuals;
  const anyUnrated = actuals.unrated;

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
                {departmentName(r.department_id, r.department_name)}
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
                {t('actuals.plan')} {fmtMoney(r.plan)}
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
        {actuals.plan !== null && (
          <span className="text-xs text-slate-500 tabular-nums">
            {t('actuals.plan')} {fmtMoney(actuals.plan)}
          </span>
        )}
        {actuals.delta !== null && (
          <span data-testid="pnl-actuals-delta"
            className={`text-xs font-medium tabular-nums ${
              Math.abs(actuals.delta) < 0.005 ? 'text-slate-400'
              : actuals.delta > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
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
  const sum = (...xs: unknown[]) => xs.reduce<number>((s, x) => s + (num(x) ?? 0), 0);
  const internalCost = totals ? sum(totals.one_time_internal, totals.lifecycle_internal) : undefined;
  const externalCost = totals ? sum(totals.one_time_external, totals.lifecycle_external) : undefined;
  const totalCost = totals ? num(totals.grand_total) ?? undefined : undefined;
  // Actual cost only means something once work is booked: before
  // implementation an empty block would read as a total of nothing.
  const actuals = data?.actuals ? normalizeActuals(data.actuals) : null;
  const showActuals = !!actuals && (actuals.hasData || ACTUALS_STATUSES.includes(change.status));

  const revenue = change.customer_relevant ? change.quoted_price : change.internal_approved_amount;
  const margin = revenue !== null && revenue !== undefined && Number.isFinite(revenue) && totalCost !== undefined
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

      {showActuals && actuals && (
        <ActualsSection actuals={actuals}
          departmentName={(id, given) => departments.find((d) => d.id === id)?.name ?? given ?? `#${id}`} />
      )}
    </div>
  );
}
