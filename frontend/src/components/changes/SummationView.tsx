import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { t } from '../../i18n/cmLabels';

export default function SummationView({ changeId }: { changeId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['change-summation', changeId],
    queryFn: () => changesApi.getSummation(changeId),
  });
  if (isLoading) return <div className="text-slate-400 text-sm p-4">Loading…</div>;
  if (!data) return null;
  const tot = data.totals;

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
          </tbody>
        </table>
      </div>

      {data.by_department.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('by_department')}</div>
          <table className="w-full text-xs">
            <thead>{breakdownHeaders}</thead>
            <tbody>
              {data.by_department.map((row) => (
                <tr key={row.department_id} className="border-b border-slate-800">
                  <td className="py-0.5">Dept #{row.department_id}</td>
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

      {data.by_plant.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-slate-300 mb-1">{t('by_plant')}</div>
          <table className="w-full text-xs">
            <thead>{breakdownHeaders}</thead>
            <tbody>
              {data.by_plant.map((row) => (
                <tr key={row.plant_id} className="border-b border-slate-800">
                  <td className="py-0.5">Plant #{row.plant_id}</td>
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
    </div>
  );
}
