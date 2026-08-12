import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { changesApi } from '../../api/changes';
import { useDepartments } from '../../hooks/queries/useWorkflows';
import {
  chosenOf, decisionDivergesOf, favoriteOf, salesEffectiveOf, tagLabel,
} from './CostPositions';
import { t } from '../../i18n/cmLabels';
import type { CostPosition } from '../../types/change';

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;

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
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not record the decision'),
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
        {t('vendor.decision')} — {t('vendor.decisionHint')}
      </div>
      <div data-testid={`vendor-recommended-${p.id}`} className="text-xs text-slate-400">
        {fav
          ? <>{t('vendor.recommended')}: <span className="text-amber-300">{fav.vendor_name} ★</span></>
          : t('vendor.noRecommendation')}
      </div>

      {chosen && (
        <div data-testid={`vendor-chosen-${p.id}`} className="text-xs text-slate-200">
          {t('vendor.chosen')}: <span className="font-semibold">{chosen.vendor_name}</span>
          {(chosen.chosen_by_name || chosen.chosen_at) && (
            <span className="text-slate-500">
              {' — '}{chosen.chosen_by_name ?? ''}
              {chosen.chosen_at && `${chosen.chosen_by_name ? ', ' : ''}${new Date(chosen.chosen_at).toLocaleDateString()}`}
            </span>
          )}
          {diverges && (
            <span data-testid={`vendor-divergence-${p.id}`}
              className="ml-2 rounded bg-amber-900/50 text-amber-200 px-1.5 py-0 text-[10px] leading-tight">
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
      <div className="flex flex-wrap items-center gap-2">
        {(p.offers ?? []).map((o) => (
          <button key={o.id} type="button" data-testid={`vendor-choose-${o.id}`}
            disabled={choose.isPending || !!o.chosen}
            onClick={() => pick(o.id)}
            className={`rounded border px-1.5 py-0.5 text-[11px] disabled:opacity-60 ${
              o.chosen
                ? 'border-sky-500 bg-sky-900/40 text-sky-200'
                : 'border-slate-600 text-slate-300 hover:bg-slate-700'}`}>
            {o.chosen ? t('vendor.chosen') : t('vendor.choose')}: {o.vendor_name}
            {o.favorite && ' ★'}
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
              className="bg-sky-600 hover:bg-sky-500 text-white px-2 py-1 rounded text-[11px] disabled:opacity-50">
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
  if (isLoading) return <div className="text-slate-400 text-sm p-4">Loading…</div>;
  if (!data) return null;
  const tot = data.totals;
  const posOf = (deptId: number) => allPositions.filter((p) => p.department_id === deptId);
  // The wrap-up counts what Sales decided to buy; the department's own block
  // keeps showing the figure its favourite carries.
  const posTotalOf = (deptId: number) =>
    posOf(deptId).reduce((s, p) => s + (salesEffectiveOf(p) ?? 0), 0);
  const positionsTotal = allPositions.reduce((s, p) => s + (salesEffectiveOf(p) ?? 0), 0);
  const canDecideVendor = canQuote && status === 'quoting';
  // Departments in position order, plus any that only show up in the summation.
  const posDeptIds = [...new Set(allPositions.map((p) => p.department_id))];

  const breakdownHeaders = (
    <tr className="text-xs text-slate-400 border-b border-slate-700">
      <th className="text-left pb-1">—</th>
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
            <tr><td>{t('one_time')} ({t('internal')})</td><td className="text-right">{tot.one_time_internal.toFixed(2)}</td></tr>
            <tr><td>{t('one_time')} ({t('external')})</td><td className="text-right">{tot.one_time_external.toFixed(2)}</td></tr>
            <tr><td>{t('lifecycle')} ({t('internal')})</td><td className="text-right">{tot.lifecycle_internal.toFixed(2)}</td></tr>
            <tr><td>{t('lifecycle')} ({t('external')})</td><td className="text-right">{tot.lifecycle_external.toFixed(2)}</td></tr>
            <tr className="border-t border-slate-600 font-semibold"><td>{t('total')}</td><td className="text-right">{tot.grand_total.toFixed(2)}</td></tr>
            {/* The positions are counted on their own line, so it stays visible
                what came from the grid and what the departments booked. */}
            {allPositions.length > 0 && (
              <>
                <tr>
                  <td>{t('costpos.title')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-positions-total">
                    {positionsTotal.toFixed(2)}
                  </td>
                </tr>
                <tr className="border-t border-slate-600 font-semibold">
                  <td>{t('summation.withPositions')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-grand-with-positions">
                    {(tot.grand_total + positionsTotal).toFixed(2)}
                  </td>
                </tr>
              </>
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
                  <span className="tabular-nums font-semibold">
                    {posTotalOf(deptId).toFixed(2)}
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
                            <span className="text-amber-300"
                              data-testid={`summation-position-vendor-${p.id}`}>
                              ★ {fav.vendor_name}
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
                              className="rounded bg-amber-900/50 text-amber-200 px-1.5 py-0 text-[10px] leading-tight">
                              {t('vendor.againstRecommendation')}
                            </span>
                          )}
                          <span className="ml-auto tabular-nums text-slate-300">
                            {(salesEffectiveOf(p) ?? 0).toFixed(2)}
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
        <div>
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('by_department')}</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-xs text-slate-400 border-b border-slate-700">
                <th className="text-left pb-1">—</th>
                <th className="text-right pb-1">{t('one_time')} {t('internal')}</th>
                <th className="text-right pb-1">{t('one_time')} {t('external')}</th>
                <th className="text-right pb-1">{t('lifecycle')} {t('internal')}</th>
                <th className="text-right pb-1">{t('lifecycle')} {t('external')}</th>
                <th className="text-right pb-1">{t('costpos.title')}</th>
                <th className="text-right pb-1">{t('total')}</th>
              </tr>
            </thead>
            <tbody>
              {data.by_department.map((row) => {
                const lines = row.one_time_internal + row.one_time_external
                  + row.lifecycle_internal + row.lifecycle_external;
                const pos = posTotalOf(row.department_id);
                return (
                  <tr key={row.department_id} className="border-b border-slate-800">
                    <td className="py-0.5">{deptName(row.department_id)}</td>
                    <td className="text-right tabular-nums">{row.one_time_internal.toFixed(2)}</td>
                    <td className="text-right tabular-nums">{row.one_time_external.toFixed(2)}</td>
                    <td className="text-right tabular-nums">{row.lifecycle_internal.toFixed(2)}</td>
                    <td className="text-right tabular-nums">{row.lifecycle_external.toFixed(2)}</td>
                    <td className="text-right tabular-nums"
                      data-testid={`summation-dept-positions-${row.department_id}`}>
                      {pos.toFixed(2)}
                    </td>
                    <td className="text-right tabular-nums font-semibold"
                      data-testid={`summation-dept-total-${row.department_id}`}>
                      {(lines + pos).toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data.by_plant.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('by_plant')}</div>
          <table className="w-full text-xs">
            <thead>{breakdownHeaders}</thead>
            <tbody>
              {data.by_plant.map((row) => (
                <tr key={row.plant_id} className="border-b border-slate-800">
                  <td className="py-0.5">{plantName(row.plant_id)}</td>
                  <td className="text-right tabular-nums">{row.one_time_internal.toFixed(2)}</td>
                  <td className="text-right tabular-nums">{row.one_time_external.toFixed(2)}</td>
                  <td className="text-right tabular-nums">{row.lifecycle_internal.toFixed(2)}</td>
                  <td className="text-right tabular-nums">{row.lifecycle_external.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Timing: the change is only as quick as its slowest department, and the
          production-time delta is what the piece price will have to carry. */}
      {(data.max_lead_time_days != null || data.total_minutes_per_part != null) && (
        <div data-testid="summation-timing">
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('summation.timing')}</div>
          <table className="w-full text-xs">
            <tbody>
              {data.max_lead_time_days != null && (
                <tr className="border-b border-slate-800">
                  <td className="py-0.5">{t('summation.maxLeadTime')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-lead-time">
                    {data.max_lead_time_days} {t('summation.days')}
                    {deadline?.date && (
                      <span className="block text-slate-500">
                        {t('summation.earliestDone')}:{' '}
                        {new Date(Date.now() + data.max_lead_time_days * 864e5).toLocaleDateString()}
                        {' · '}{deadline.label}:{' '}
                        {new Date(deadline.date).toLocaleDateString()}
                        {Date.now() + data.max_lead_time_days * 864e5
                          > new Date(deadline.date).getTime() && (
                          <span className="text-red-400"> ⚠ {t('summation.pastDeadline')}</span>
                        )}
                      </span>
                    )}
                  </td>
                </tr>
              )}
              {(data.lifecycle_minutes_by_plant ?? []).map((row) => (
                <tr key={row.plant_id} className="border-b border-slate-800">
                  <td className="py-0.5">{plantName(row.plant_id)}</td>
                  <td className="text-right tabular-nums">
                    {row.minutes_per_part > 0 ? '+' : ''}{row.minutes_per_part} {t('summation.perPart')}
                  </td>
                </tr>
              ))}
              {data.total_minutes_per_part != null && (
                <tr className="font-semibold">
                  <td>{t('costing.minutesShort')}</td>
                  <td className="text-right tabular-nums" data-testid="summation-minutes">
                    {data.total_minutes_per_part > 0 ? '+' : ''}{data.total_minutes_per_part}
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
                  <td className="text-right tabular-nums">{row.effort_hours.toFixed(2)} h</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td>{t('total')}</td>
                <td className="text-right tabular-nums">{data.total_effort_hours.toFixed(2)} h</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
