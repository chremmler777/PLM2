import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { t } from '../../i18n/cmLabels';

export default function SummationView({ changeId }: { changeId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['change-summation', changeId], queryFn: () => changesApi.getSummation(changeId) });
  if (isLoading) return <div className="text-slate-400 text-sm p-4">Loading…</div>;
  if (!data) return null;
  const tot = data.totals;
  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 text-sm text-slate-200">
      <div className="font-semibold text-slate-100 mb-2">Summierung</div>
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
  );
}
