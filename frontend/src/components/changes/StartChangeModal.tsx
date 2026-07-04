import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import client from '../../api/client';
import { changesApi } from '../../api/changes';
import { useAuth } from '../../contexts/AuthContext';
import { t } from '../../i18n/cmLabels';
import type { ChangeType } from '../../types/change';

export const CHANGE_TYPES: { value: ChangeType; label: string }[] = [
  { value: 'physical_part', label: 'Physical Part' },
  { value: 'tooling', label: 'Tooling' },
  { value: 'document_spec', label: 'Document / Spec' },
  { value: 'process_im', label: 'Process / IM' },
  { value: 'packaging', label: 'Packaging' },
];

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;

const inferType = (category: string): ChangeType =>
  ['tool', 'gauge', 'equipment'].includes(category) ? 'tooling' : 'physical_part';

interface PickedPart {
  id: number;
  part_number: string;
  name: string;
  item_category: string;
}

export interface StartChangePrefill {
  projectId?: number;
  part?: PickedPart;
}

export interface StartChangeModalProps {
  open: boolean;
  onClose: () => void;
  prefill?: StartChangePrefill;
}

interface ProjectRef {
  id: number;
  name: string;
}

export default function StartChangeModal({ open, onClose, prefill }: StartChangeModalProps) {
  const navigate = useNavigate();
  const { userId } = useAuth();

  const projectLocked = prefill?.projectId != null;
  const [projectId, setProjectId] = useState<number | undefined>(prefill?.projectId);
  const [picked, setPicked] = useState<PickedPart | undefined>(prefill?.part);
  const [search, setSearch] = useState('');
  const [title, setTitle] = useState('');
  const [reason, setReason] = useState('');
  const [typeTouched, setTypeTouched] = useState(false);
  const [overrideType, setOverrideType] = useState<ChangeType>('physical_part');
  const [submitting, setSubmitting] = useState(false);

  const changeType: ChangeType = typeTouched
    ? overrideType
    : picked
    ? inferType(picked.item_category)
    : 'physical_part';

  const { data: projects = [] } = useQuery<ProjectRef[]>({
    queryKey: ['projects'],
    queryFn: async () => (await client.get('/v1/plants/projects')).data,
    enabled: open,
  });

  const { data: parts = [] } = useQuery<PickedPart[]>({
    queryKey: ['project-parts', projectId],
    queryFn: async () => (await client.get(`/v1/parts/project/${projectId}`)).data,
    enabled: open && !!projectId,
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const matches = q
      ? parts.filter(
          (p) =>
            p.part_number.toLowerCase().includes(q) ||
            p.name.toLowerCase().includes(q),
        )
      : parts;
    const articles = matches.filter((p) => p.item_category === 'article');
    const tools = matches.filter((p) => p.item_category !== 'article');
    return { articles, tools };
  }, [parts, search]);

  const lockedProjectName = useMemo(
    () => projects.find((p) => p.id === projectId)?.name,
    [projects, projectId],
  );

  if (!open) return null;

  const canSubmit = !!projectId && !!picked && !!title.trim() && !submitting;

  const handleSubmit = async () => {
    if (!projectId || !picked || !title.trim()) return;
    setSubmitting(true);
    try {
      const change = await changesApi.create({
        project_id: projectId,
        title: title.trim(),
        change_type: changeType,
        reason: reason.trim() || undefined,
        lead_id: userId ?? undefined,
      });
      try {
        await changesApi.addImpactedItem(change.id, { part_id: picked.id, is_lead: true });
      } catch (e) {
        toast.error(errDetail(e) ?? 'Could not attach the lead item — add it in the impact tree.');
      }
      onClose();
      navigate(`/changes/${change.id}`);
    } catch (e) {
      toast.error(errDetail(e) ?? 'Could not start the change.');
    } finally {
      setSubmitting(false);
    }
  };

  const selectPart = (p: PickedPart) => {
    setPicked(p);
    setTypeTouched(false);
    setSearch('');
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 text-slate-100 rounded-xl border border-slate-700 shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold">{t('start.title')}</h2>
          <button
            className="text-slate-400 hover:text-slate-200 text-xl leading-none"
            onClick={onClose}
            aria-label={t('common.close')}
          >
            ×
          </button>
        </div>

        {/* Project */}
        <div className="mb-4">
          <label htmlFor="sc-project" className="block text-sm text-slate-300 mb-1">
            {t('start.project')}
          </label>
          {projectLocked ? (
            <div
              id="sc-project"
              className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200"
            >
              {lockedProjectName ?? `#${projectId}`}
            </div>
          ) : (
            <select
              id="sc-project"
              className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
              value={projectId ?? ''}
              onChange={(e) => {
                setProjectId(e.target.value ? Number(e.target.value) : undefined);
                setPicked(undefined);
                setTypeTouched(false);
              }}
            >
              <option value="">—</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Item picker */}
        <div className="mb-4">
          <label htmlFor="sc-item" className="block text-sm text-slate-300 mb-1">
            {t('start.item')}
          </label>
          {picked ? (
            <div className="flex items-center gap-2 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm">
              <span className="font-mono text-slate-100">{picked.part_number}</span>
              <span className="text-slate-400 truncate">{picked.name}</span>
              <button
                type="button"
                className="ml-auto text-slate-400 hover:text-slate-200"
                onClick={() => setPicked(undefined)}
                aria-label={t('start.clearItem')}
              >
                ✕
              </button>
            </div>
          ) : (
            <>
              <input
                id="sc-item"
                type="text"
                className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
                placeholder={t('start.searchItem')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                disabled={!projectId}
              />
              {projectId && (
                <div className="mt-2 max-h-52 overflow-y-auto rounded-lg border border-slate-700 divide-y divide-slate-700/60">
                  {filtered.articles.length > 0 && (
                    <div>
                      <div className="px-3 py-1 text-xs uppercase tracking-wide text-slate-500 bg-slate-900/60">
                        {t('start.articles')}
                      </div>
                      {filtered.articles.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          className="w-full text-left px-3 py-2 text-sm hover:bg-slate-700/50 flex items-center gap-2"
                          onClick={() => selectPart(p)}
                        >
                          <span className="font-mono text-slate-100">{p.part_number}</span>
                          <span className="text-slate-400 truncate">{p.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {filtered.tools.length > 0 && (
                    <div>
                      <div className="px-3 py-1 text-xs uppercase tracking-wide text-slate-500 bg-slate-900/60">
                        {t('start.tools')}
                      </div>
                      {filtered.tools.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          className="w-full text-left px-3 py-2 text-sm hover:bg-slate-700/50 flex items-center gap-2"
                          onClick={() => selectPart(p)}
                        >
                          <span className="font-mono text-slate-100">{p.part_number}</span>
                          <span className="text-slate-400 truncate">{p.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {filtered.articles.length === 0 && filtered.tools.length === 0 && (
                    <div className="px-3 py-3 text-sm text-slate-500">{t('start.noMatches')}</div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Title */}
        <div className="mb-4">
          <label htmlFor="sc-title" className="block text-sm text-slate-300 mb-1">
            {t('start.changeTitle')}
          </label>
          <input
            id="sc-title"
            type="text"
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        {/* Change type */}
        <div className="mb-4">
          <label htmlFor="sc-type" className="block text-sm text-slate-300 mb-1">
            {t('start.type')}
          </label>
          <select
            id="sc-type"
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
            value={changeType}
            onChange={(e) => {
              setTypeTouched(true);
              setOverrideType(e.target.value as ChangeType);
            }}
          >
            {CHANGE_TYPES.map((ct) => (
              <option key={ct.value} value={ct.value}>
                {ct.label}
              </option>
            ))}
          </select>
        </div>

        {/* Reason */}
        <div className="mb-6">
          <label htmlFor="sc-reason" className="block text-sm text-slate-300 mb-1">
            {t('start.reason')}
          </label>
          <textarea
            id="sc-reason"
            rows={3}
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <div className="flex justify-end gap-2">
          <button
            className="px-4 py-2 text-sm text-slate-300 hover:text-slate-100"
            onClick={onClose}
          >
            {t('common.cancel')}
          </button>
          <button
            className="px-4 py-2 rounded-lg bg-sky-600 text-white text-sm font-medium hover:bg-sky-500 disabled:opacity-50"
            disabled={!canSubmit}
            onClick={handleSubmit}
          >
            {t('start.create')}
          </button>
        </div>
      </div>
    </div>
  );
}
