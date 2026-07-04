import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { changesApi } from '../../api/changes';
import type { ImplementationItem } from '../../types/change';
import { t } from '../../i18n/cmLabels';
import ReasonDialog from './ReasonDialog';
import CADUploader from '../CADUploader';
import RevisionWorkflowSection from '../workflows/RevisionWorkflowSection';

interface Props {
  changeId: number;
}

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export default function ImplementationPanel({ changeId }: Props) {
  const qc = useQueryClient();
  const [signTarget, setSignTarget] = useState<ImplementationItem | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [uploadFor, setUploadFor] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['change', changeId, 'implementation'],
    queryFn: () => changesApi.getImplementation(changeId),
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ['change', changeId, 'implementation'] });

  const sign = useMutation({
    mutationFn: ({ item, reason }: { item: ImplementationItem; reason: string }) =>
      changesApi.signNoGeometryChange(item.part_id, item.revision_id!, reason),
    onSuccess: () => {
      setSignTarget(null);
      invalidate();
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Sign-off failed'),
  });

  if (isLoading || !data) return <div className="text-slate-400 text-sm">…</div>;

  return (
    <div className="space-y-4">
      <div
        data-testid="ready-banner"
        className={`rounded-lg border p-3 text-sm font-semibold ${
          data.ready_to_go
            ? 'bg-emerald-900/40 border-emerald-700 text-emerald-200'
            : 'bg-slate-800 border-slate-700 text-slate-300'
        }`}
      >
        {data.ready_to_go ? `✓ ${t('impl.readyToGo')}` : t('impl.notReady')}
      </div>

      {data.items.map((item) => {
        const evidenceOk = item.has_cad_file || item.no_geometry_change;
        return (
          <div
            key={item.item_id}
            className="bg-slate-800 rounded-lg border border-slate-700 p-4"
          >
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-slate-100 font-medium">
                {item.part_name}{' '}
                <span className="text-slate-500 text-xs">{item.part_number}</span>
              </span>
              {item.revision_name ? (
                <span className="px-2 py-0.5 rounded-full text-xs bg-purple-900 text-purple-100">
                  {item.revision_name}
                </span>
              ) : (
                <span className="text-slate-400 text-xs">{t('impl.noRevision')}</span>
              )}
              {item.instance_status && (
                <span
                  className={`px-2 py-0.5 rounded-full text-xs ${
                    item.ready ? 'bg-emerald-900 text-emerald-100' : 'bg-blue-900 text-blue-100'
                  }`}
                >
                  {item.ready
                    ? '✓'
                    : `${t('impl.stage')} ${item.current_stage_order}/${item.total_stages}`}{' '}
                  {item.instance_status}
                </span>
              )}
              <span
                className={`px-2 py-0.5 rounded-full text-xs ${
                  evidenceOk ? 'bg-emerald-900 text-emerald-100' : 'bg-amber-900 text-amber-100'
                }`}
              >
                {evidenceOk
                  ? item.no_geometry_change
                    ? t('impl.noGeometry')
                    : t('impl.evidenceOk')
                  : t('impl.evidenceMissing')}
              </span>
            </div>

            {!evidenceOk && item.revision_id !== null && (
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={() =>
                    setUploadFor(uploadFor === item.item_id ? null : item.item_id)
                  }
                  className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs"
                >
                  Upload CAD
                </button>
                <button
                  onClick={() => setSignTarget(item)}
                  className="px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs"
                >
                  {t('impl.signNoGeometry')}
                </button>
              </div>
            )}
            {uploadFor === item.item_id && item.revision_id !== null && (
              <div className="mt-3">
                <CADUploader
                  partId={item.part_id}
                  revisionId={item.revision_id}
                  compact
                  onUploadSuccess={() => {
                    setUploadFor(null);
                    invalidate();
                  }}
                />
              </div>
            )}

            {item.revision_id !== null && item.instance_id !== null && (
              <div className="mt-3">
                <button
                  onClick={() =>
                    setExpanded(expanded === item.item_id ? null : item.item_id)
                  }
                  className="text-sky-400 hover:text-sky-300 text-xs"
                >
                  {expanded === item.item_id ? '▾ Workflow' : '▸ Workflow'}
                </button>
                {expanded === item.item_id && (
                  <div className="mt-2">
                    <RevisionWorkflowSection
                      revisionId={item.revision_id}
                      revisionName={item.revision_name ?? undefined}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      <ReasonDialog
        open={signTarget !== null}
        title={t('impl.signNoGeometry')}
        label={t('impl.signNoGeometry')}
        submitLabel="Confirm"
        onSubmit={(reason: string) =>
          signTarget && sign.mutate({ item: signTarget, reason })
        }
        onClose={() => setSignTarget(null)}
      />
    </div>
  );
}
