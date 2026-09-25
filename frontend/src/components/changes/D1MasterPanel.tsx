import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { changesApi } from '../../api/changes';
import { plantsApi } from '../../api/plants';
import type { Gate, GateKey, ChangeDetail, ImpactTreeNode } from '../../types/change';
import { t } from '../../i18n/cmLabels';
import { COST_CARRIER_LABELS } from '../../lib/humanLabels';
import { formatDate } from '../../lib/format';
import { toastError } from '../../lib/apiError';
import { useAuth } from '../../contexts/AuthContext';
import Button from '../common/Button';
import EmptyState from '../common/EmptyState';

/** A finished change keeps its D1 as a record: nothing on it is edited. */
const FINISHED = new Set(['closed', 'cancelled', 'rejected']);

/** Who pays may only move while the change is captured or being scoped. */
const CARRIER_OPEN = new Set(['captured', 'scoping']);

/** The gate answers as people say them. */
const DECISION_LABEL: Record<'yes' | 'no' | 'na', string> = { yes: 'Yes', no: 'No', na: 'N/A' };

/** The backend may name the decider; older responses carry only the id. */
type NamedGate = Gate & { decided_by_name?: string | null };

const inputCls =
  'bg-slate-900 border border-slate-600 rounded-md px-2 py-1 text-slate-100 text-xs ' +
  'focus:border-sky-500 focus:outline-none disabled:cursor-not-allowed disabled:text-slate-400 disabled:bg-slate-900/50';

interface D1Fields {
  issuer: string;
  car_line: string;
  is_series: boolean;
  cm_internal: boolean;
  cm_external: boolean;
  implementation_mode: '' | 'integrated' | 'separational';
  customer_relevant: boolean;
  affected_plant_ids: number[];
}

function fieldsFromChange(c: ChangeDetail): D1Fields {
  return {
    issuer: c.issuer ?? '',
    car_line: c.car_line ?? '',
    is_series: c.is_series ?? false,
    cm_internal: c.cm_internal ?? false,
    cm_external: c.cm_external ?? false,
    implementation_mode: (c.implementation_mode as D1Fields['implementation_mode']) ?? '',
    customer_relevant: c.customer_relevant ?? false,
    affected_plant_ids: c.affected_plant_ids ?? [],
  };
}

/**
 * Rights mirror the backend PATCH gate: the D1 master data is the lead's,
 * Quality's and Project Management's (plus admin); customer relevance is the
 * lead's (plus admin). Without a right the field is shown read-only.
 */
export default function D1MasterPanel({
  changeId, canEditD1 = false, canEditCustomerRelevant = false,
}: {
  changeId: number;
  canEditD1?: boolean;
  canEditCustomerRelevant?: boolean;
}) {
  const qc = useQueryClient();
  const { userId, isAdmin } = useAuth();

  const { data: change } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
  });

  const { data: gates = [] } = useQuery({
    queryKey: ['change-gates', changeId],
    queryFn: () => changesApi.getGates(changeId),
  });
  // Part numbers and names for the impacted items, from the impact tree the
  // Impacted tab already loads (same cache entry), so D1 never says "Part 2279".
  const needsPartNames = (change?.impacted_items ?? []).some((i) => !i.part_number);
  const { data: impactTree, isLoading: treeLoading } = useQuery({
    queryKey: ['change', changeId, 'impact-tree'],
    queryFn: () => changesApi.getImpactTree(changeId),
    enabled: needsPartNames,
    retry: false,
  });
  const partOf = (partId: number): { number: string; name: string } | null => {
    let hit: ImpactTreeNode | null = null;
    const walk = (n: ImpactTreeNode) => {
      if (hit) return;
      if (n.part_id === partId) { hit = n; return; }
      n.children.forEach(walk);
    };
    (impactTree?.tree ?? []).forEach(walk);
    const found = hit as ImpactTreeNode | null;
    return found ? { number: found.part_number, name: found.name } : null;
  };
  // Who decided a gate, by name: the backend's name when it sends one, else
  // the people the change can name (its lead candidates). Never a bare "#16".
  const namedGates = gates as NamedGate[];
  const needsDeciders = namedGates.some((g) => g.decided_by != null && !g.decided_by_name);
  const { data: people = [] } = useQuery({
    queryKey: ['change', changeId, 'lead-candidates', 'd1'],
    queryFn: async () => {
      try { return await changesApi.leadCandidates(changeId); } catch { return []; }
    },
    enabled: needsDeciders,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  const deciderName = (g: NamedGate): string | null =>
    g.decided_by_name ?? people.find((p) => p.id === g.decided_by)?.name ?? null;

  const { data: plants = [] } = useQuery({
    queryKey: ['plants'],
    queryFn: plantsApi.list,
  });
  // Inactive plants (e.g. "Main Factory" test data) are never selectable here.
  const allPlants = plants.filter((p) => p.is_active !== false);

  const [fields, setFields] = useState<D1Fields>({
    issuer: '', car_line: '', is_series: false, cm_internal: false,
    cm_external: false, implementation_mode: '', customer_relevant: false,
    affected_plant_ids: [],
  });
  const [seeded, setSeeded] = useState(false);

  useEffect(() => {
    if (change && !seeded) {
      setFields(fieldsFromChange(change));
      setSeeded(true);
    }
  }, [change, seeded]);

  const updateChange = useMutation({
    mutationFn: (body: Record<string, unknown>) => changesApi.update(changeId, body),
    onSuccess: () => {
      toast.success('D1 fields saved');
      qc.invalidateQueries({ queryKey: ['change', changeId] });
    },
    onError: (e: unknown) => { toastError(e, 'Could not save the D1 fields'); },
  });

  const decide = useMutation({
    mutationFn: ({ key, decision }: { key: GateKey; decision: string }) =>
      changesApi.putGate(changeId, key, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change-gates', changeId] }),
    onError: (e: unknown) => { toastError(e, 'Could not record the gate decision'); },
  });

  // A finished change is a record: every control reads, none edits.
  const finished = !!change && FINISHED.has(change.status);
  const mayEditD1 = canEditD1 && !finished;
  // Mirrors the backend: the cost carrier moves only during capture or
  // scoping, and never on a mother-plant change (the mother plant handles
  // the customer there).
  const mayEditCarrier = canEditCustomerRelevant && !finished && !!change
    && CARRIER_OPEN.has(change.status) && change.origin !== 'mother_plant';
  // Gates are the change lead's decision (or an admin's); everyone else reads.
  const mayDecide = !!change && (isAdmin || (userId != null && change.lead_id === userId));

  const togglePlant = (plantId: number) => {
    setFields((f) => {
      const ids = f.affected_plant_ids.includes(plantId)
        ? f.affected_plant_ids.filter((id) => id !== plantId)
        : [...f.affected_plant_ids, plantId];
      return { ...f, affected_plant_ids: ids };
    });
  };

  // Only what actually changed, and only what this user may change: a stale
  // or untouched field (say customer_relevant) must not 403 the whole save.
  const handleSave = () => {
    if (!change) return;
    const base = fieldsFromChange(change);
    const body: Record<string, unknown> = {};
    if (mayEditD1) {
      if (fields.issuer !== base.issuer) body.issuer = fields.issuer || null;
      if (fields.car_line !== base.car_line) body.car_line = fields.car_line || null;
      if (fields.is_series !== base.is_series) body.is_series = fields.is_series;
      if (fields.cm_internal !== base.cm_internal) body.cm_internal = fields.cm_internal;
      if (fields.cm_external !== base.cm_external) body.cm_external = fields.cm_external;
      if (fields.implementation_mode !== base.implementation_mode) {
        body.implementation_mode = fields.implementation_mode || null;
      }
      const sorted = (ids: number[]) => [...ids].sort((a, b) => a - b).join(',');
      if (sorted(fields.affected_plant_ids) !== sorted(base.affected_plant_ids)) {
        body.affected_plant_ids = fields.affected_plant_ids;
      }
    }
    if (mayEditCarrier && fields.customer_relevant !== base.customer_relevant) {
      body.customer_relevant = fields.customer_relevant;
    }
    if (Object.keys(body).length === 0) return;
    updateChange.mutate(body);
  };
  const canSave = mayEditD1 || mayEditCarrier;

  const leadItem = change?.impacted_items?.find((i) => i.is_lead);

  return (
    // A finished change says so once, in the page's own closed banner; here
    // the controls simply read.
    <div className="rounded-xl border border-slate-700 bg-slate-800/40 p-4 space-y-5" data-testid="d1-panel"
      data-readonly={finished || undefined}>
      {/* D1 header fields */}
      <div>
        <h3 className="text-sm font-semibold text-slate-100 mb-2">D1 fields</h3>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <label className="flex flex-col gap-0.5">
            <span className="text-slate-400 text-xs">{t('issuer')}</span>
            <input
              className={inputCls}
              value={fields.issuer}
              disabled={!mayEditD1}
              onChange={(e) => setFields((f) => ({ ...f, issuer: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-slate-400 text-xs">{t('car_line')}</span>
            <input
              className={inputCls}
              value={fields.car_line}
              disabled={!mayEditD1}
              onChange={(e) => setFields((f) => ({ ...f, car_line: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-slate-400 text-xs">{t('implementation_mode')}</span>
            <select
              className={inputCls}
              value={fields.implementation_mode}
              disabled={!mayEditD1}
              onChange={(e) => setFields((f) => ({ ...f, implementation_mode: e.target.value as D1Fields['implementation_mode'] }))}
            >
              <option value="">-</option>
              <option value="integrated">{t('integrated')}</option>
              <option value="separational">{t('separational')}</option>
            </select>
          </label>
          <div className="flex flex-col gap-1 pt-1">
            {([
              ['is_series', 'is_series'],
              ['cm_internal', 'cm_internal'],
              ['cm_external', 'cm_external'],
            ] as const).map(([key, labelKey]) => (
              <label key={key} className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-sky-500"
                  checked={fields[key]}
                  disabled={!mayEditD1}
                  onChange={(e) => setFields((f) => ({ ...f, [key]: e.target.checked }))}
                />
                {t(labelKey)}
              </label>
            ))}
            {/* Cost carrier reads the same here as at the scoping meeting:
                who pays, in words, not a bare checkbox. */}
            <label className="flex flex-col gap-0.5 pt-1">
              <span className="text-slate-400 text-xs">{t('customer_relevant')}</span>
              <select data-testid="d1-cost-carrier"
                className={inputCls}
                value={fields.customer_relevant ? 'customer' : 'internal'}
                disabled={!mayEditCarrier}
                onChange={(e) => setFields((f) => ({ ...f, customer_relevant: e.target.value === 'customer' }))}>
                <option value="customer">{COST_CARRIER_LABELS.customer}</option>
                <option value="internal">{COST_CARRIER_LABELS.internal}</option>
              </select>
            </label>
          </div>
        </div>
      </div>

      {/* Affected plants */}
      <div>
        <h4 className="text-xs font-semibold text-slate-300 mb-1">{t('affected_plants')}</h4>
        <div className="flex flex-wrap gap-2">
          {allPlants.map((p) => (
            <label key={p.id} className="flex items-center gap-1 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                className="accent-sky-500"
                checked={fields.affected_plant_ids.includes(p.id)}
                disabled={!mayEditD1}
                onChange={() => togglePlant(p.id)}
              />
              {p.name} ({p.code})
            </label>
          ))}
          {allPlants.length === 0 && <span className="text-slate-400 text-xs">No active plants</span>}
        </div>
      </div>

      {/* Impacted items / Leit-Teil */}
      <div>
        <h4 className="text-xs font-semibold text-slate-300 mb-1">{t('impacted_items')}</h4>
        {change?.impacted_items && change.impacted_items.length > 0 ? (
          <ul className="text-xs space-y-1">
            {change.impacted_items.map((item) => {
              const known = item.part_number
                ? { number: item.part_number, name: item.part_name ?? '' }
                : partOf(item.part_id);
              return (
                <li key={item.id} data-testid={`d1-item-${item.id}`}
                  className="flex min-w-0 items-center gap-1.5 text-slate-300">
                  {known ? (
                    <>
                      <span className="font-mono text-slate-100">{known.number}</span>
                      {known.name && <span className="truncate text-slate-400">{known.name}</span>}
                    </>
                  ) : (
                    <span className="text-slate-400">{treeLoading ? 'Loading the part…' : 'Part not found in this project'}</span>
                  )}
                  {item.is_lead && (
                    <span className="flex-shrink-0 px-1.5 py-0.5 rounded bg-sky-900/60 text-sky-200 text-[11px] font-medium">
                      {t('lead_part')}
                    </span>
                  )}
                  {item.impact_note && <span className="text-slate-400">: {item.impact_note}</span>}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState size="sm" title="No impacted items yet"
            hint={leadItem ? undefined : `${t('no_lead_set')}. Pick the parts on the Impacted tab.`} />
        )}
      </div>

      {/* Save button: only for someone who may change something here */}
      {canSave && <div className="flex justify-end">
        <Button variant="primary" size="sm" onClick={handleSave} loading={updateChange.isPending}>
          {updateChange.isPending ? t('saving') : t('save')}
        </Button>
      </div>}

      {/* Gates */}
      <div>
        <h3 className="text-sm font-semibold text-slate-100 mb-2">Final assessment</h3>
        <div className="space-y-2">
          {namedGates.map((g) => {
            const key = g.gate_key;
            const decidedAt = g?.decided_at ? formatDate(g.decided_at) : null;
            const decidedBy = g?.decided_by != null ? deciderName(g) : null;
            return (
              <div key={key} className="text-sm" data-testid={`d1-gate-${key}`}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-200" id={`d1-gate-label-${key}`}>{t(key)}</span>
                  {!mayDecide ? (
                    <span className="text-xs font-medium text-slate-200" data-testid={`d1-gate-value-${key}`}
                      aria-labelledby={`d1-gate-label-${key}`}>
                      {g?.decision ? DECISION_LABEL[g.decision] : 'Not decided'}
                    </span>
                  ) : (
                  <span className="inline-flex overflow-hidden rounded-md border border-slate-600 divide-x divide-slate-600"
                    role="group" aria-labelledby={`d1-gate-label-${key}`}>
                    {(['yes', 'no', 'na'] as const).map((d) => (
                      <button
                        key={d}
                        type="button"
                        aria-pressed={g?.decision === d}
                        disabled={finished || decide.isPending}
                        onClick={() => decide.mutate({ key, decision: d })}
                        className={`min-w-[2.75rem] px-2 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400 disabled:cursor-not-allowed ${g?.decision === d
                          ? 'bg-sky-700 text-white'
                          : 'bg-slate-900 text-slate-300 hover:bg-slate-800 disabled:hover:bg-slate-900 disabled:text-slate-500'}`}
                      >
                        {DECISION_LABEL[d]}
                      </button>
                    ))}
                  </span>
                  )}
                </div>
                {g?.decision && (decidedBy || decidedAt) && (
                  <div className="text-xs text-slate-400 mt-0.5 pl-1" data-testid={`d1-gate-decided-${key}`}>
                    {decidedBy ? `${t('decided_by')} ${decidedBy}` : 'Decided'}
                    {decidedAt ? ` on ${decidedAt}` : ''}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
