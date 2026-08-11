import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import client from '../../api/client';
import { changesApi } from '../../api/changes';
import { useAuth } from '../../contexts/AuthContext';
import { t } from '../../i18n/cmLabels';
import { groupItems } from '../../lib/itemCategory';
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
// 40 = resin/material, 65 = returnables/dunnage, which get their own flows
// later. A change type with no entry here imposes no prefix filter.
const partPrefix = (partNumber: string): string => partNumber.split('-')[0];
const TYPE_PART_PREFIXES: Partial<Record<ChangeType, Set<string>>> = {
  physical_part: new Set(['10', '11', '20', '22']),
};

// Types whose picker offers articles only. A physical-part change never targets
// a mold or a gauge directly — the tool follows from the article, via the
// tooling flow. Tooling / process changes will opt back in when they land.
const TYPES_WITHOUT_TOOLS: Set<ChangeType> = new Set(['physical_part']);

// A change is named after the item it changes, our number first:
//   <our number>[ +n] - <customer number> - <item name>
//   20-3454-001-0 +2 - 3CR.807.425 - RR Cladding (Basis)
//   3454 - Rear Cladding                     (a tool has no customer number)
// The project is deliberately absent — every change already carries its
// project, and repeating "1864 VW426 Atlas" on every row buys nothing. Nobody
// types a title; it is derived, so an ECR and the documents belonging to it
// read alike and sort together. The lead item names the change; siblings
// riding along on the same request are counted with "+n".
export const REASON_MAX_LENGTH = 100;
const TITLE_MAX_LENGTH = 255;

export function composeTitle(picked: PickedPart[]): string {
  const lead = picked[0];
  if (!lead) return '';
  const others = picked.length - 1;
  const ours = others > 0 ? `${lead.part_number} +${others}` : lead.part_number;
  const parts = [ours, lead.customer_part_number, lead.name].filter(Boolean);
  return parts.join(' - ').slice(0, TITLE_MAX_LENGTH);
}

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;

interface PickedPart {
  id: number;
  part_number: string;
  customer_part_number?: string | null;
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
  // Several items can ride on one change request — a tool family (all four
  // 3457 parts, say) is normally reworked together, so it is one ECR with one
  // set of assessments and one revision per part. picked[0] is the lead item.
  const [picked, setPicked] = useState<PickedPart[]>(prefill?.part ? [prefill.part] : []);
  const [search, setSearch] = useState('');
  const [reason, setReason] = useState('');
  // Change type is chosen up front and scopes the item picker. Only physical-part
  // changes are enabled today (see ENABLED_CHANGE_TYPES).
  const [changeType, setChangeType] = useState<ChangeType>('physical_part');
  const [customerRelevant, setCustomerRelevant] = useState<boolean | undefined>(undefined);
  const [submitting, setSubmitting] = useState(false);
  // Server-side refusals (e.g. 403 for a user outside a change-starting
  // department) are shown in place, not only as a toast that scrolls away.
  const [createError, setCreateError] = useState<string | null>(null);

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

  const pickedIds = useMemo(() => new Set(picked.map((p) => p.id)), [picked]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const pool = parts.filter((p) => !pickedIds.has(p.id));
    const matches = q
      ? pool.filter(
          (p) =>
            p.part_number.toLowerCase().includes(q) ||
            (p.customer_part_number ?? '').toLowerCase().includes(q) ||
            p.name.toLowerCase().includes(q),
        )
      : pool;
    const allArticles = matches.filter((p) => p.item_category === 'article');
    const equipment = TYPES_WITHOUT_TOOLS.has(changeType)
      ? []
      : matches.filter((p) => p.item_category !== 'article');
    // Scope articles to the selected change type's part families (physical parts
    // only, today). Anything outside is hidden but counted, so it never looks
    // like the project simply has no parts.
    const allow = TYPE_PART_PREFIXES[changeType];
    const articles = allow
      ? allArticles.filter((p) => allow.has(partPrefix(p.part_number)))
      : allArticles;
    // Articles and equipment are bucketed together: the split people care about
    // is Articles / Dunnage / Material / Tools / EOAT / …, not article-vs-not.
    return {
      groups: groupItems([...articles, ...equipment]),
      hiddenArticles: allArticles.length - articles.length,
    };
  }, [parts, search, changeType, pickedIds]);

  const project = useMemo(
    () => projects.find((pr) => pr.id === projectId), [projects, projectId]);
  const lockedProjectName = project ? projectLabel(project) : undefined;

  const title = useMemo(() => composeTitle(picked), [picked]);

  if (!open) return null;

  const missing: string[] = [];
  if (!projectId) missing.push('project');
  if (picked.length === 0) missing.push('affected item');
  if (!reason.trim()) missing.push('reason');
  if (customerRelevant === undefined) missing.push('cost carrier');

  const canSubmit = missing.length === 0 && !!title && !submitting;

  const handleSubmit = async () => {
    if (missing.length > 0 || !projectId || picked.length === 0 || !title) return;
    setSubmitting(true);
    setCreateError(null);
    try {
      const change = await changesApi.create({
        project_id: projectId,
        title,
        change_type: changeType,
        reason: reason.trim() || undefined,
        lead_id: userId ?? undefined,
        customer_relevant: customerRelevant,
      });
      // Sequential on purpose: the lead item must land first, and a partial
      // failure has to name the parts that did not attach so they can be added
      // in the impact tree instead of vanishing silently.
      const failed: string[] = [];
      for (const [i, p] of picked.entries()) {
        try {
          await changesApi.addImpactedItem(change.id, { part_id: p.id, is_lead: i === 0 });
        } catch {
          failed.push(p.part_number);
        }
      }
      if (failed.length > 0) {
        toast.error(
          `Could not attach ${failed.join(', ')} — add ${failed.length > 1 ? 'them' : 'it'} in the impact tree.`,
        );
      }
      onClose();
      navigate(`/changes/${change.id}`);
    } catch (e) {
      const message = errDetail(e) ?? 'Could not start the change.';
      setCreateError(message);
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  // The picker stays open and the query is kept, so sibling parts of the same
  // tool can be added one after another without retyping the search.
  const selectPart = (p: PickedPart) => {
    setPicked((prev) => (prev.some((x) => x.id === p.id) ? prev : [...prev, p]));
  };

  const removePart = (id: number) =>
    setPicked((prev) => prev.filter((p) => p.id !== id));

  const makeLead = (id: number) =>
    setPicked((prev) => {
      const target = prev.find((p) => p.id === id);
      return target ? [target, ...prev.filter((p) => p.id !== id)] : prev;
    });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 text-slate-100 rounded-xl border border-slate-700 shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto p-6">
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
                setPicked([]);
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
            {picked.length > 0 && (
              <span className="ml-2 text-xs text-slate-500">
                {t('start.selectedCount').replace('{n}', String(picked.length))}
              </span>
            )}
          </label>
          <p className="mb-2 text-xs text-slate-500">{t('start.itemHint')}</p>

          {/* Chosen items — first row is the lead; the rest ride along on the
              same request and each get their own revision on release. */}
          {picked.length > 0 && (
            <ul className="mb-2 space-y-1">
              {picked.map((p, i) => (
                <li
                  key={p.id}
                  className="flex items-center gap-2 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm whitespace-nowrap overflow-hidden"
                >
                  <span className="font-mono text-slate-100 flex-shrink-0 w-36">{p.part_number}</span>
                  <span className="font-mono text-sky-300/80 flex-shrink-0 w-32">
                    {p.customer_part_number ?? <span className="text-slate-600">—</span>}
                  </span>
                  <span className="text-slate-400 truncate min-w-0">{p.name}</span>
                  {i === 0 ? (
                    <span className="ml-auto flex-shrink-0 rounded bg-sky-900/60 text-sky-300 px-1.5 py-0.5 text-xs">
                      {t('start.lead')}
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="ml-auto flex-shrink-0 text-xs text-slate-500 hover:text-sky-300"
                      onClick={() => makeLead(p.id)}
                      aria-label={`${t('start.makeLead')}: ${p.part_number}`}
                    >
                      {t('start.makeLead')}
                    </button>
                  )}
                  <button
                    type="button"
                    className="flex-shrink-0 text-slate-400 hover:text-slate-200"
                    onClick={() => removePart(p.id)}
                    aria-label={`${t('start.clearItem')}: ${p.part_number}`}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}

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
            <div className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-slate-700 divide-y divide-slate-700/60">
              <div className="flex items-center gap-2 px-3 py-1.5 text-xs uppercase tracking-wide text-slate-500 bg-slate-900/60 sticky top-0">
                <span className="flex-shrink-0 w-36">{t('start.colInternal')}</span>
                <span className="flex-shrink-0 w-32">{t('start.colCustomer')}</span>
                <span className="min-w-0">{t('start.colName')}</span>
              </div>
              {/* One block per category, separated by a rule. Articles come
                  first — the common change target — then dunnage, material and
                  the equipment classes. */}
              {filtered.groups.map((group) => (
                <div key={group.key} className="border-t border-slate-700 first:border-t-0">
                  <div className="px-3 py-1.5 flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500 bg-slate-900/40">
                    <span className="truncate">{group.label}</span>
                    <span className="ml-auto flex-shrink-0 normal-case">{group.items.length}</span>
                  </div>
                  {group.items.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className="w-full text-left px-3 py-2 text-sm hover:bg-slate-700/50 flex items-center gap-2 whitespace-nowrap overflow-hidden"
                      onClick={() => selectPart(p)}
                    >
                      <span className="font-mono text-slate-100 flex-shrink-0 w-36">{p.part_number}</span>
                      <span className="font-mono text-sky-300/80 flex-shrink-0 w-32">
                        {p.customer_part_number ?? <span className="text-slate-600">—</span>}
                      </span>
                      <span className="text-slate-400 truncate min-w-0">{p.name}</span>
                    </button>
                  ))}
                </div>
              ))}

              {filtered.groups.length === 0 && (
                <div className="px-3 py-3 text-sm text-slate-500">{t('start.noMatches')}</div>
              )}
              {filtered.hiddenArticles > 0 && (
                <div className="px-3 py-1.5 text-xs text-slate-500 bg-slate-900/40">
                  {t('start.hiddenNonPhysical').replace('{n}', String(filtered.hiddenArticles))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Title — derived, never typed. Shown so the name is no surprise. */}
        <div className="mb-4">
          <label htmlFor="sc-title" className="block text-sm text-slate-300 mb-1">
            {t('start.changeTitle')}
          </label>
          <output
            id="sc-title"
            className="block w-full rounded-lg bg-slate-900/60 border border-dashed border-slate-700 px-3 py-2 text-sm truncate"
          >
            {title || <span className="text-slate-600">{t('start.titlePlaceholder')}</span>}
          </output>
          <p className="mt-1 text-xs text-slate-500">{t('start.titleAuto')}</p>
        </div>

        {/* Reason */}
        <div className="mb-6">
          <label htmlFor="sc-reason" className="flex items-baseline gap-2 text-sm text-slate-300 mb-1">
            <span>{t('start.reason')}</span>
            <span
              className={`ml-auto text-xs tabular-nums ${
                reason.length >= REASON_MAX_LENGTH ? 'text-amber-400' : 'text-slate-500'
              }`}
            >
              {reason.length}/{REASON_MAX_LENGTH}
            </span>
          </label>
          <input
            id="sc-reason"
            type="text"
            maxLength={REASON_MAX_LENGTH}
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
            placeholder={t('start.reasonPlaceholder')}
            value={reason}
            onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX_LENGTH))}
          />
          <p className="mt-1 text-xs text-slate-500">{t('start.reasonHint')}</p>
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
                <span className="text-slate-100">{t('start.customerChange')}</span>
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
                <span className="text-slate-100">{t('start.internalChange')}</span>
                <span className="block text-xs text-slate-500">{t('start.customerRelevantNoHint')}</span>
              </span>
            </label>
          </div>
        </fieldset>

        {createError && (
          <p role="alert" data-testid="start-error"
            className="mb-3 rounded-lg border border-red-800/60 bg-red-950/40 px-3 py-2 text-sm text-red-200">
            {createError}
          </p>
        )}

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
