import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { useDepartments } from '../../hooks/queries/useWorkflows';
import { effectiveOf, tagLabel } from './CostPositions';
import { t } from '../../i18n/cmLabels';

export default function SummationView({
  changeId, deadline, plants = [], validatedWeightG = null,
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
  const posTotalOf = (deptId: number) =>
    posOf(deptId).reduce((s, p) => s + (effectiveOf(p) ?? 0), 0);
  const positionsTotal = allPositions.reduce((s, p) => s + (effectiveOf(p) ?? 0), 0);
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
                    const fav = (p.offers ?? []).find((o) => o.favorite);
                    return (
                      <li key={p.id} data-testid={`summation-position-${p.id}`}
                        className="flex items-baseline gap-2 border-b border-slate-800 py-0.5">
                        <span className="text-slate-200">{p.label}</span>
                        {p.tag && <span className="text-slate-500">{tagLabel(p.tag)}</span>}
                        <span className="text-slate-500">{t(`costpos.kind.${p.kind}`)}</span>
                        {fav && (
                          <span className="text-amber-300"
                            data-testid={`summation-position-vendor-${p.id}`}>
                            ★ {fav.vendor_name}
                          </span>
                        )}
                        <span className="ml-auto tabular-nums text-slate-300">
                          {(effectiveOf(p) ?? 0).toFixed(2)}
                        </span>
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
