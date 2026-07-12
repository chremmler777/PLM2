import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import type { ChangeDetail, ChangeStatus } from '../../types/change';

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
export default function PnlCard({ change }: { change: ChangeDetail }) {
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
    </div>
  );
}
