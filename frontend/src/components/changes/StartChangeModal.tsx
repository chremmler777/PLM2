import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import client from '../../api/client';
import { changesApi } from '../../api/changes';
import { useAuth } from '../../contexts/AuthContext';
import { t } from '../../i18n/cmLabels';
import type { ChangeType } from '../../types/change';

// Full vocabulary the backend understands. Kept for typing and future rollout.
export const CHANGE_TYPES: { value: ChangeType; label: string }[] = [
  { value: 'physical_part', label: 'Physical Part' },
  { value: 'tooling', label: 'Tooling' },
  { value: 'document_spec', label: 'Document / Spec' },
  { value: 'process_im', label: 'Process / IM' },
  { value: 'packaging', label: 'Packaging' },
];

// Types offered in the UI today. We start with physical-part changes (the most
// common) and add tooling / process / material / packaging as each flow is ready.
export const ENABLED_CHANGE_TYPES: ChangeType[] = ['physical_part'];

// WinCarat encodes the real part class in the number prefix (all rows are
// item_category 'article' in PLM). Physical parts are the 10/11/20/22 families;
// 40 = packaging, 65 = material, etc. get their own flows later. A change type
// with no entry here imposes no prefix filter.
const partPrefix = (partNumber: string): string => partNumber.split('-')[0];
const TYPE_PART_PREFIXES: Partial<Record<ChangeType, Set<string>>> = {
  physical_part: new Set(['10', '11', '20', '22']),
};

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;

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
  code: string;
  name: string;
}

// Projects read number-first: "1864 · VW426 Atlas".
const projectLabel = (p: ProjectRef): string =>
  p.code ? `${p.code} · ${p.name}` : p.name;

export default function StartChangeModal({ open, onClose, prefill }: StartChangeModalProps) {
  const navigate = useNavigate();
  const { userId } = useAuth();

  const projectLocked = prefill?.projectId != null;
  const [projectId, setProjectId] = useState<number | undefined>(prefill?.projectId);
  const [picked, setPicked] = useState<PickedPart | undefined>(prefill?.part);
  const [search, setSearch] = useState('');
  const [title, setTitle] = useState('');
  const [reason, setReason] = useState('');
  // Change type is chosen up front and scopes the item picker. Only physical-part
  // changes are enabled today (see ENABLED_CHANGE_TYPES).
  const [changeType, setChangeType] = useState<ChangeType>('physical_part');
  const [customerRelevant, setCustomerRelevant] = useState<boolean | undefined>(undefined);
  const [submitting, setSubmitting] = useState(false);
  const [showTools, setShowTools] = useState(false);

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
    const allArticles = matches.filter((p) => p.item_category === 'article');
    const tools = matches.filter((p) => p.item_category !== 'article');
    // Scope articles to the selected change type's part families (physical parts
    // only, today). Anything outside is hidden but counted, so it never looks
    // like the project simply has no parts.
    const allow = TYPE_PART_PREFIXES[changeType];
    const articles = allow
      ? allArticles.filter((p) => allow.has(partPrefix(p.part_number)))
      : allArticles;
    return { articles, tools, hiddenArticles: allArticles.length - articles.length };
  }, [parts, search, changeType]);

  const lockedProjectName = useMemo(() => {
    const p = projects.find((pr) => pr.id === projectId);
    return p ? projectLabel(p) : undefined;
  }, [projects, projectId]);

  if (!open) return null;

  const missing: string[] = [];
  if (!projectId) missing.push('project');
  if (!picked) missing.push('affected item');
  if (!title.trim()) missing.push('title');
  if (!reason.trim()) missing.push('reason');
  if (customerRelevant === undefined) missing.push('customer-relevant choice');

  const canSubmit = missing.length === 0 && !submitting;

  const handleSubmit = async () => {
    if (missing.length > 0 || !projectId || !picked) return;
    setSubmitting(true);
    try {
      const change = await changesApi.create({
        project_id: projectId,
        title: title.trim(),
        change_type: changeType,
        reason: reason.trim() || undefined,
        lead_id: userId ?? undefined,
        customer_relevant: customerRelevant,
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
              }}
            >
              <option value="">—</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {projectLabel(p)}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Change type — chosen up front; scopes which items the picker offers.
            Only physical-part changes are enabled today; more are added over time. */}
        <div className="mb-4">
          <label htmlFor="sc-type" className="block text-sm text-slate-300 mb-1">
            {t('start.type')}
          </label>
          <select
            id="sc-type"
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
            value={changeType}
            onChange={(e) => setChangeType(e.target.value as ChangeType)}
          >
            {ENABLED_CHANGE_TYPES.map((v) => (
              <option key={v} value={v}>
                {CHANGE_TYPES.find((ct) => ct.value === v)?.label ?? v}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">{t('start.typeMoreSoon')}</p>
        </div>

        {/* Item picker */}
        <div className="mb-4">
          <label htmlFor="sc-item" className="block text-sm text-slate-300 mb-1">
            {t('start.item')}
          </label>
          {picked ? (
            <div className="flex items-center gap-2 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm whitespace-nowrap overflow-hidden">
              <span className="font-mono text-slate-100 flex-shrink-0">{picked.part_number}</span>
              <span className="text-slate-400 truncate min-w-0">{picked.name}</span>
              <button
                type="button"
                className="ml-auto flex-shrink-0 text-slate-400 hover:text-slate-200"
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
                  {/* Articles — the common change target, always open on top. */}
                  {filtered.articles.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className="w-full text-left px-3 py-2 text-sm hover:bg-slate-700/50 flex items-center gap-2 whitespace-nowrap overflow-hidden"
                      onClick={() => selectPart(p)}
                    >
                      <span className="font-mono text-slate-100 flex-shrink-0">{p.part_number}</span>
                      <span className="text-slate-400 truncate min-w-0">{p.name}</span>
                    </button>
                  ))}

                  {/* Tools & equipment — rarely changed alone, collapsed by default. */}
                  {filtered.tools.length > 0 && (
                    <div>
                      <button
                        type="button"
                        className="w-full text-left px-3 py-2 flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500 bg-slate-900/60 hover:text-slate-300"
                        onClick={() => setShowTools((v) => !v)}
                      >
                        <span className="flex-shrink-0">{showTools ? '▾' : '▸'}</span>
                        <span className="truncate">{t('start.toolsRarely')}</span>
                        <span className="ml-auto flex-shrink-0 normal-case">{filtered.tools.length}</span>
                      </button>
                      {showTools && (
                        <>
                          <p className="px-3 py-2 text-xs text-slate-500 bg-slate-900/40 normal-case">
                            {t('start.toolsNote')}
                          </p>
                          {filtered.tools.map((p) => (
                            <button
                              key={p.id}
                              type="button"
                              className="w-full text-left px-3 py-2 text-sm hover:bg-slate-700/50 flex items-center gap-2 whitespace-nowrap overflow-hidden"
                              onClick={() => selectPart(p)}
                            >
                              <span className="font-mono text-slate-100 flex-shrink-0">{p.part_number}</span>
                              <span className="text-slate-400 truncate min-w-0">{p.name}</span>
                            </button>
                          ))}
                        </>
                      )}
                    </div>
                  )}

                  {filtered.articles.length === 0 && filtered.tools.length === 0 && (
                    <div className="px-3 py-3 text-sm text-slate-500">{t('start.noMatches')}</div>
                  )}
                  {filtered.hiddenArticles > 0 && (
                    <div className="px-3 py-1.5 text-xs text-slate-500 bg-slate-900/40">
                      {t('start.hiddenNonPhysical').replace('{n}', String(filtered.hiddenArticles))}
                    </div>
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

        {/* Customer-relevant */}
        <fieldset className="mb-6">
          <legend className="block text-sm text-slate-300 mb-1">{t('start.customerRelevant')}</legend>
          <div className="space-y-2">
            <label className="flex items-start gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="sc-customer-relevant"
                className="mt-1"
                checked={customerRelevant === true}
                onChange={() => setCustomerRelevant(true)}
              />
              <span>
                <span className="text-slate-100">{t('common.yes')}</span>
                <span className="block text-xs text-slate-500">{t('start.customerRelevantYesHint')}</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="sc-customer-relevant"
                className="mt-1"
                checked={customerRelevant === false}
                onChange={() => setCustomerRelevant(false)}
              />
              <span>
                <span className="text-slate-100">{t('common.no')}</span>
                <span className="block text-xs text-slate-500">{t('start.customerRelevantNoHint')}</span>
              </span>
            </label>
          </div>
        </fieldset>

        <div className="flex justify-end items-center gap-3">
          {missing.length > 0 && !submitting && (
            <p className="text-xs text-slate-400">
              {t('start.missing')}: {missing.join(', ')}
            </p>
          )}
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
