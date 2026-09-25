import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { formatMoney } from '../../lib/format';
import type { ChangeDetail, ChangeStatus } from '../../types/change';
import OfferVsActualSection from './pnl/OfferVsActualSection';
import ActualCostsPanel from './pnl/ActualCostsPanel';

const HIDDEN_STATUSES: ChangeStatus[] = ['captured', 'scoping', 'in_assessment'];
/** Stages where there is doing: offer vs actual and actual costs. */
const ACTUALS_STATUSES: ChangeStatus[] = ['in_implementation', 'in_validation', 'released', 'closed'];

/** "13.629,50 EUR" via the shared formatter — same money format everywhere. */
const fmtMoney = (v: number | null | undefined, currency?: string | null) =>
  v === null || v === undefined || !Number.isFinite(v) ? '-' : formatMoney(v, currency);

function marginAccent(v: number | null | undefined): string {
  if (v === null || v === undefined || Math.abs(v) < 0.005) return 'text-slate-400';
  return v > 0 ? 'text-emerald-400' : 'text-red-400';
}

/** A finite number, or null: NaN and missing fields never reach the card. */
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null

/**
 * Compact per-change P&L card for the commercial cockpit tab. Semantics
 * mirror PnlPage/Task 1: customer-relevant changes show a quoted-price
 * "Revenue" figure and a real "Margin"; internal changes show the
 * PM-approved budget snapshot and label the delta "vs. approved budget"
 * (never "profit"). Hidden entirely before costing (captured, scoping,
 * in_assessment) since there's no meaningful cost data yet.
 */
export default function PnlCard({ change, departments = [], canSeeCosts = true }: {
  change: ChangeDetail;
  /** Only used to name the actual-cost rows; absent is a legible fallback. */
  departments?: { id: number; name: string }[];
  /**
   * PM, Sales, the lead, admin. Anyone else gets only the actual costs of
   * their own department (the server lists and accepts nothing more), and
   * no request for the whole P&L is made.
   */
  canSeeCosts?: boolean;
}) {
  const hidden = HIDDEN_STATUSES.includes(change.status);

  const { data } = useQuery({
    queryKey: ['change-summation', change.id],
    queryFn: () => changesApi.getSummation(change.id),
    enabled: !hidden && canSeeCosts,
  });

  if (hidden) return null;
  if (!canSeeCosts) {
    if (!ACTUALS_STATUSES.includes(change.status)) return null;
    return (
      <div data-testid="pnl-department-costs" className="bg-slate-800 border border-slate-700 rounded-lg px-4 pb-4 mb-4 empty:hidden">
        <ActualCostsPanel changeId={change.id} departments={departments} />
      </div>
    );
  }

  const totals = data?.totals;
  const sum = (...xs: unknown[]) => xs.reduce<number>((s, x) => s + (num(x) ?? 0), 0);
  const internalCost = totals ? sum(totals.one_time_internal, totals.lifecycle_internal) : undefined;
  const externalCost = totals ? sum(totals.one_time_external, totals.lifecycle_external) : undefined;
  const totalCost = totals ? num(totals.grand_total) ?? undefined : undefined;

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

      {/* Offer versus doing (spec §13): only once there is doing. Before
          implementation the card is the plan alone. */}
      {ACTUALS_STATUSES.includes(change.status) && (
        <OfferVsActualSection changeId={change.id} departments={departments} />
      )}

    </div>
  );
}
