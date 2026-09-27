import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { toastError } from '../../lib/apiError';
import { useDepartments } from '../../hooks/queries/useWorkflows';
import {
  alternativesOf, chosenOf, decisionDivergesOf, favoriteOf, partsOf, tagLabel,
} from './CostPositions';
import { t } from '../../i18n/cmLabels';
import { addDaysIso, daysUntil, formatCalendarDate, formatDate, formatDays, formatHours, formatMoney, formatNumber, todayIso } from '../../lib/format';
import { CircleAlert, Star } from 'lucide-react';
import { LoadingSkeleton } from '../common/LoadingSkeleton';
import { btnSm } from '../common/buttonStyles';
import type { CostPosition, SummationPositionLine } from '../../types/change';

/**
 * Sales' vendor decision on one quoted position.
 *
 * The department's favourite is a recommendation and stays named as one. Sales
 * makes the binding call here and answers for it: picking anything else needs a
 * written reason before it goes anywhere, and the divergence stays marked on the
 * position afterwards. Both figures stay readable side by side — the wish and
 * the decision.
 */
function VendorDecision({ changeId, position }: { changeId: number; position: CostPosition }) {
  const qc = useQueryClient();
  const [pendingOfferId, setPendingOfferId] = useState<number | null>(null);
  const [reason, setReason] = useState('');
  const p = position;
  const fav = favoriteOf(p);
  const chosen = chosenOf(p);
  const diverges = decisionDivergesOf(p);

  const choose = useMutation({
    mutationFn: (v: { offerId: number; reason?: string }) =>
      changesApi.chooseCostingOffer(changeId, v.offerId, v.reason),
    onSuccess: () => {
      setPendingOfferId(null);
      setReason('');
      qc.invalidateQueries({ queryKey: ['costing-positions', changeId] });
      qc.invalidateQueries({ queryKey: ['change-summation', changeId] });
    },
    onError: (e: unknown) => toastError(e, 'Could not record the decision'),
  });

  const pick = (offerId: number) => {
    // The favourite needs no defence; anything else does, and the reason box
    // opens before a single request goes out.
    if (fav && offerId !== fav.id) {
      setPendingOfferId(offerId);
      setReason('');
      return;
    }
    choose.mutate({ offerId });
  };

  return (
    <div data-testid={`vendor-decision-${p.id}`}
      className="mt-1 ml-2 border-l border-slate-700 pl-2 space-y-1">
      <div className="text-[11px] text-slate-500">
        {t('vendor.decision')}: {t('vendor.decisionHint')}
      </div>
      <div data-testid={`vendor-recommended-${p.id}`} className="text-xs text-slate-400">
        {fav
          ? <>{t('vendor.recommended')}: <span className="inline-flex items-center gap-1 text-amber-300">{fav.vendor_name}<Star aria-hidden="true" size={11} fill="currentColor" /></span></>
          : t('vendor.noRecommendation')}
      </div>

      {chosen && (
        <div data-testid={`vendor-chosen-${p.id}`} className="text-xs text-slate-200">
          {t('vendor.chosen')}: <span className="font-semibold">{chosen.vendor_name}</span>
          {(chosen.chosen_by_name || chosen.chosen_at) && (
            <span className="text-slate-500">
              {', '}{chosen.chosen_by_name ?? ''}
              {chosen.chosen_at && `${chosen.chosen_by_name ? ', ' : ''}${formatDate(chosen.chosen_at)}`}
            </span>
          )}
          {diverges && (
            <span data-testid={`vendor-divergence-${p.id}`}
              className="ml-2 rounded bg-amber-900/50 text-amber-200 px-1.5 py-0 text-[11px] leading-tight">
              {t('vendor.againstRecommendation')}
            </span>
          )}
          {chosen.chosen_reason && (
            <span data-testid={`vendor-chosen-reason-${p.id}`}
              className="block text-slate-400">{chosen.chosen_reason}</span>
          )}
        </div>
      )}

      {/* Re-choosing stays open while the change is being quoted. */}
      {partsOf(p).length > 0 && (
        <div data-testid={`vendor-parts-${p.id}`} className="text-xs text-slate-400">
          {t('costpos.partsSum')}: {partsOf(p).map((o) => { const v = o.cost + (o.shipping_included ? 0 : o.shipping_cost ?? 0); return `${o.vendor_name} ${p.currency ? formatMoney(v, p.currency) : formatNumber(v, { min: 2, max: 2 })}`; }).join(' + ')}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {alternativesOf(p).map((o) => (
          <button key={o.id} type="button" data-testid={`vendor-choose-${o.id}`}
            disabled={choose.isPending || !!o.chosen}
            onClick={() => pick(o.id)}
            className={`rounded border px-1.5 py-0.5 text-[11px] disabled:opacity-60 ${
              o.chosen
                ? 'border-sky-500 bg-sky-900/40 text-sky-200'
                : 'border-slate-600 text-slate-300 hover:bg-slate-700'}`}>
            {o.chosen ? t('vendor.chosen') : t('vendor.choose')}: {o.vendor_name}
            {o.favorite && (
              <>
                <Star aria-hidden="true" size={11} fill="currentColor" className="ml-1 inline text-amber-300" />
                <span className="sr-only"> ({t('vendor.recommended')})</span>
              </>
            )}
          </button>
        ))}
      </div>

      {pendingOfferId != null && (
        <div data-testid={`vendor-reason-${p.id}`} className="space-y-1">
          <label className="block text-[11px] text-amber-300"
            htmlFor={`vendor-reason-input-${p.id}`}>
            {t('vendor.reasonLabel')}
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input id={`vendor-reason-input-${p.id}`}
              data-testid={`vendor-reason-input-${p.id}`}
              aria-label={t('vendor.reasonLabel')} value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 flex-1 min-w-[12rem]" />
            <button type="button" data-testid={`vendor-reason-confirm-${p.id}`}
              disabled={reason.trim() === '' || choose.isPending}
              onClick={() => choose.mutate({ offerId: pendingOfferId, reason: reason.trim() })}
              className={btnSm.primary}>
              {t('vendor.confirm')}
            </button>
            <button type="button" data-testid={`vendor-reason-cancel-${p.id}`}
              onClick={() => { setPendingOfferId(null); setReason(''); }}
              className="text-slate-400 hover:text-slate-200 text-[11px]">
              {t('vendor.cancel')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SummationView({
  changeId, deadline, plants = [], validatedWeightG = null,
  status, canQuote = false,
}: {
  changeId: number
  /** The deadline the timing roll-up is measured against, when there is one. */
  deadline?: { date: string | null; label: string }
  plants?: { id: number; name: string }[]
  /**
   * The weight once somebody has checked it against a real part. Until that
   * exists the Tool Engineer's figure is shown as the estimate it is.
   */
  validatedWeightG?: number | null
  /** Where the change stands — the vendor decision is a quoting-stage act. */
  status?: string
  /** Sales, the lead or an admin: the people who answer for the price. */
  canQuote?: boolean
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['change-summation', changeId],
    queryFn: () => changesApi.getSummation(changeId),
  });
  const { data: departments = [] } = useDepartments();
  // The departments' cost positions ride along with the summation: they are the
  // other half of what a department books, and Sales quotes off the pair.
  const { data: allPositions = [] } = useQuery({
    queryKey: ['costing-positions', changeId],
    queryFn: () => changesApi.listCostPositions(changeId),
  });
  const deptName = (id: number) =>
    departments.find((d) => d.id === id)?.name ?? `#${id}`;
  const plantName = (id: number) => plants.find((p) => p.id === id)?.name ?? `Plant #${id}`;
  if (isLoading) return <LoadingSkeleton count={2} />;
  if (!data) return null;
  const tot = data.totals;
  // Every figure below is the backend's, in the costing currency: the
  // positions are already inside the totals and the department rows (their
  // quoted money and their hours priced from the cost sheet), so they are
  // shown as a part of the total, never added to it again.
  const cur = data.currency ?? 'EUR';
  const money = (v: number | null | undefined) => formatMoney(v ?? 0, cur);
  const rollups = data.positions_by_department ?? [];
  const rollupOf = (deptId: number) => rollups.find((r) => r.department_id === deptId);
  const rollupTotal = (deptId: number) => {
    const r = rollupOf(deptId);
    return r ? r.position_cost + r.hours_cost : 0;
  };
  const positionsTotal = (data.total_position_cost ?? 0) + (data.total_position_hours_cost ?? 0);
  const costLinesTotal = tot.grand_total - positionsTotal;
  const hasPositions = rollups.length > 0;
  const lineOf = (p: CostPosition): SummationPositionLine | undefined =>
    rollupOf(p.department_id)?.positions.find((l) => l.position_id === p.id);
  /** A position's share of the total: its quoted money plus its priced hours. */
  const lineAmount = (p: CostPosition): string => {
    const l = lineOf(p);
    if (!l) return '-';
    const valueCur = p.rate_currency ?? cur;
    // hours without a rate: not counted, and not shown as a 0
    if (l.line_value === null && !l.cost) return '-';
    const value = l.line_value ?? 0;
    if (l.currency === valueCur || !value || !l.cost) {
      return formatMoney(l.cost + value, value ? valueCur : l.currency);
    }
    return `${formatMoney(l.cost, l.currency)} + ${formatMoney(value, valueCur)}`;
  };
  const posOf = (deptId: number) => allPositions.filter((p) => p.department_id === deptId);
  const canDecideVendor = canQuote && status === 'quoting';
  // Departments in position order, plus any that only show up in the summation.
  const posDeptIds = [...new Set(allPositions.map((p) => p.department_id))];
  // Nothing costed gives 0 d and +0 min/part: noise, not data. Shown once real.
  const leadDays = data.max_lead_time_days ?? 0;
  const minuteRows = (data.lifecycle_minutes_by_plant ?? []).filter((r) => r.minutes_per_part !== 0);
  const totalMinutes = data.total_minutes_per_part ?? 0;

  const breakdownHeaders = (
    <tr className="text-xs text-slate-400 border-b border-slate-700">
      <th className="text-left pb-1"><span className="sr-only">{t('by_plant')}</span></th>
      <th className="text-right pb-1">{t('one_time')} {t('internal')}</th>
      <th className="text-right pb-1">{t('one_time')} {t('external')}</th>
      <th className="text-right pb-1">{t('lifecycle')} {t('internal')}</th>
      <th className="text-right pb-1">{t('lifecycle')} {t('external')}</th>
    </tr>
  );

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 text-sm text-slate-200 space-y-4">
      <div>
        <div className="font-semibold text-slate-100 mb-2">{t('summierung')}</div>
        <table className="w-full">
          <tbody>
            <tr><td>{t('one_time')} ({t('internal')})</td><td className="text-right tabular-nums">{money(tot.one_time_internal)}</td></tr>
            <tr><td>{t('one_time')} ({t('external')})</td><td className="text-right tabular-nums">{money(tot.one_time_external)}</td></tr>
            <tr><td>{t('lifecycle')} ({t('internal')})</td><td className="text-right tabular-nums">{money(tot.lifecycle_internal)}</td></tr>
            <tr><td>{t('lifecycle')} ({t('external')})</td><td className="text-right tabular-nums">{money(tot.lifecycle_external)}</td></tr>
            {hasPositions ? (
              <>
                {/* The four rows above hold everything; below they split into
                    what the cost lines booked and what the positions did. */}
                <tr className="border-t border-slate-600 font-semibold">
                  <td>{t('summation.costLines')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-total">
                    {money(costLinesTotal)}
                  </td>
                </tr>
                <tr>
                  <td>{t('costpos.title')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-positions-total">
                    {money(positionsTotal)}
                  </td>
                </tr>
                <tr className="border-t border-slate-600 font-semibold">
                  <td>{t('summation.withPositions')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-grand-with-positions">
                    {money(tot.grand_total)}
                  </td>
                </tr>
              </>
            ) : (
              <tr className="border-t border-slate-600 font-semibold">
                <td>{t('total')}</td>
                <td className="text-right tabular-nums" data-testid="summation-total">
                  {money(tot.grand_total)}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {/* Not money, so it sits below the money rather than inside it — but
            Sales quotes off it, so it belongs on the same card. It reads as an
            estimate until the validated figure exists. */}
        {data.part_weight_estimate_g != null && (
          <div data-testid="summation-part-weight"
            className="flex justify-between pt-2 text-xs text-slate-300">
            <span>
              {validatedWeightG != null
                ? t('summation.partWeight')
                : t('summation.partWeightEstimate')}
            </span>
            <span className="tabular-nums">
              {validatedWeightG ?? data.part_weight_estimate_g} {t('summation.grams')}
            </span>
          </div>
        )}
      </div>

      {/* What each department actually booked, position by position — with the
          vendor whose offer the department picked, because that is the price
          the total is built on. */}
      {posDeptIds.length > 0 && (
        <div data-testid="summation-positions">
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('costpos.title')}</div>
          <div className="space-y-2">
            {posDeptIds.map((deptId) => (
              <div key={deptId} data-testid={`summation-positions-dept-${deptId}`}>
                <div className="flex justify-between text-xs text-slate-300">
                  <span>{deptName(deptId)}</span>
                  <span className="tabular-nums font-semibold"
                    data-testid={`summation-positions-dept-total-${deptId}`}>
                    {money(rollupTotal(deptId))}
                  </span>
                </div>
                <ul className="text-xs">
                  {posOf(deptId).map((p) => {
                    const fav = favoriteOf(p);
                    const chosen = chosenOf(p);
                    // A quoted external position with offers is a decision Sales
                    // owes; everything else is just a figure.
                    const decidable = p.kind === 'external' && p.pricing === 'quote'
                      && (p.offers ?? []).length > 0;
                    return (
                      <li key={p.id} data-testid={`summation-position-${p.id}`}
                        className="border-b border-slate-800 py-0.5">
                        <div className="flex items-baseline gap-2">
                          <span className="text-slate-200">{p.label}</span>
                          {p.tag && <span className="text-slate-500">{tagLabel(p.tag)}</span>}
                          <span className="text-slate-500">{t(`costpos.kind.${p.kind}`)}</span>
                          {fav && (
                            <span className="inline-flex items-center gap-1 text-amber-300"
                              data-testid={`summation-position-vendor-${p.id}`}
                              title={t('vendor.recommended')}>
                              <Star aria-hidden="true" size={11} fill="currentColor" />{fav.vendor_name}
                            </span>
                          )}
                          {chosen && (
                            <span className="text-sky-300"
                              data-testid={`summation-position-chosen-${p.id}`}>
                              {t('vendor.chosen')}: {chosen.vendor_name}
                            </span>
                          )}
                          {decisionDivergesOf(p) && (
                            <span data-testid={`summation-position-divergence-${p.id}`}
                              className="rounded bg-amber-900/50 text-amber-200 px-1.5 py-0 text-[11px] leading-tight">
                              {t('vendor.againstRecommendation')}
                            </span>
                          )}
                          {/* Hours, machine hours or trials priced from the cost
                              sheet (already inside the totals above). */}
                          {(p.kind === 'sampling' ? (p.trials ?? 0) : (p.hours ?? 0)) > 0 && (
                            <span data-testid={`summation-position-value-${p.id}`}
                              className={p.rate_missing ? 'text-amber-300' : 'text-slate-500'}>
                              {p.kind === 'sampling' ? `${formatNumber(p.trials)} ${t('costpos.trialsShort')}` : formatHours(p.hours)}
                              {' · '}
                              {p.rate_missing ? t('costpos.noRate')
                                : p.line_value != null ? formatMoney(p.line_value, p.rate_currency ?? cur) : '-'}
                            </span>
                          )}
                          <span className="ml-auto tabular-nums text-slate-300"
                            data-testid={`summation-position-amount-${p.id}`}>
                            {lineAmount(p)}
                          </span>
                        </div>
                        {canDecideVendor && decidable && (
                          <VendorDecision changeId={changeId} position={p} />
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.by_department.length > 0 && (
        <div className="overflow-x-auto">
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('by_department')}</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-xs text-slate-400 border-b border-slate-700">
                <th className="text-left pb-1"><span className="sr-only">{t('by_department')}</span></th>
                <th className="text-right pb-1">{t('one_time')} {t('internal')}</th>
                <th className="text-right pb-1">{t('one_time')} {t('external')}</th>
                <th className="text-right pb-1">{t('lifecycle')} {t('internal')}</th>
                <th className="text-right pb-1">{t('lifecycle')} {t('external')}</th>
                <th className="text-right pb-1" title={t('summation.positionsPart')}>
                  {t('costpos.title')}
                </th>
                <th className="text-right pb-1">{t('total')}</th>
              </tr>
            </thead>
            <tbody>
              {data.by_department.map((row) => {
                // The row total is the backend's: the positions are inside
                // its columns already, and the positions column only says
                // how much of it they are.
                const total = row.one_time_internal + row.one_time_external
                  + row.lifecycle_internal + row.lifecycle_external;
                return (
                  <tr key={row.department_id} className="border-b border-slate-800">
                    <td className="py-0.5">{deptName(row.department_id)}</td>
                    <td className="text-right tabular-nums">{money(row.one_time_internal)}</td>
                    <td className="text-right tabular-nums">{money(row.one_time_external)}</td>
                    <td className="text-right tabular-nums">{money(row.lifecycle_internal)}</td>
                    <td className="text-right tabular-nums">{money(row.lifecycle_external)}</td>
                    <td className="text-right tabular-nums text-slate-400"
                      data-testid={`summation-dept-positions-${row.department_id}`}>
                      {money(rollupTotal(row.department_id))}
                    </td>
                    <td className="text-right tabular-nums font-semibold"
                      data-testid={`summation-dept-total-${row.department_id}`}>
                      {money(total)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data.by_plant.length > 0 && (
        <div className="overflow-x-auto">
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('by_plant')}</div>
          <table className="w-full text-xs">
            <thead>{breakdownHeaders}</thead>
            <tbody>
              {data.by_plant.map((row) => (
                <tr key={row.plant_id} className="border-b border-slate-800">
                  <td className="py-0.5">{plantName(row.plant_id)}</td>
                  <td className="text-right tabular-nums">{formatMoney(row.one_time_internal, row.currency ?? cur)}</td>
                  <td className="text-right tabular-nums">{formatMoney(row.one_time_external, row.currency ?? cur)}</td>
                  <td className="text-right tabular-nums">{formatMoney(row.lifecycle_internal, row.currency ?? cur)}</td>
                  <td className="text-right tabular-nums">{formatMoney(row.lifecycle_external, row.currency ?? cur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Timing: the change is only as quick as its slowest department, and the
          production-time delta is what the piece price will have to carry. */}
      {(leadDays > 0 || minuteRows.length > 0 || totalMinutes !== 0) && (
        <div data-testid="summation-timing">
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('summation.timing')}</div>
          <table className="w-full text-xs">
            <tbody>
              {leadDays > 0 && (
                <tr className="border-b border-slate-800">
                  <td className="py-0.5">{t('summation.maxLeadTime')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-lead-time">
                    {formatDays(leadDays)}
                    {deadline?.date && (
                      <span className="block text-slate-500">
                        {t('summation.earliestDone')}:{' '}
                        {formatCalendarDate(addDaysIso(todayIso(), Math.ceil(leadDays)))}
                        {' · '}{deadline.label}:{' '}
                        {formatCalendarDate(deadline.date)}
                        {Math.ceil(leadDays) > daysUntil(deadline.date) && (
                          <span className="inline-flex items-center gap-1 text-red-300">
                            {' '}<CircleAlert aria-hidden="true" size={12} />{t('summation.pastDeadline')}
                          </span>
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              )}
              {minuteRows.map((row) => (
                <tr key={row.plant_id} className="border-b border-slate-800">
                  <td className="py-0.5">{plantName(row.plant_id)}</td>
                  <td className="text-right tabular-nums">
                    {formatNumber(row.minutes_per_part, { sign: true })} {t('summation.perPart')}
                  </td>
                </tr>
              ))}
              {totalMinutes !== 0 && (
                <tr className="font-semibold">
                  <td>{t('costing.minutesShort')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-minutes">
                    {formatNumber(totalMinutes, { sign: true })}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {data.total_effort_hours > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('effort.total')}</div>
          <table className="w-full text-xs">
            <tbody>
              {data.effort_by_department.map((row) => (
                <tr key={row.department_id} className="border-b border-slate-800">
                  <td className="py-0.5">{deptName(row.department_id)}</td>
                  <td className="text-right tabular-nums">{formatHours(row.effort_hours)}</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td>{t('total')}</td>
                <td className="text-right tabular-nums">{formatHours(data.total_effort_hours)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
