import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import { plantsApi } from '../../api/plants';
import type { Gate, GateKey, ChangeDetail } from '../../types/change';
import { t } from '../../i18n/cmLabels';

const GATES: GateKey[] = ['feasibility', 'budget', 'release'];

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

export default function D1MasterPanel({ changeId }: { changeId: number }) {
  const qc = useQueryClient();

  const { data: change } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
  });

  const { data: gates = [] } = useQuery({
    queryKey: ['change-gates', changeId],
    queryFn: () => changesApi.getGates(changeId),
  });

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId] }),
  });

  const decide = useMutation({
    mutationFn: ({ key, decision }: { key: GateKey; decision: string }) =>
      changesApi.putGate(changeId, key, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change-gates', changeId] }),
  });

  const byKey: Record<string, Gate> = Object.fromEntries(gates.map((g) => [g.gate_key, g]));

  const togglePlant = (plantId: number) => {
    setFields((f) => {
      const ids = f.affected_plant_ids.includes(plantId)
        ? f.affected_plant_ids.filter((id) => id !== plantId)
        : [...f.affected_plant_ids, plantId];
      return { ...f, affected_plant_ids: ids };
    });
  };

  const handleSave = () => {
    updateChange.mutate({
      issuer: fields.issuer || null,
      car_line: fields.car_line || null,
      is_series: fields.is_series,
      cm_internal: fields.cm_internal,
      cm_external: fields.cm_external,
      implementation_mode: fields.implementation_mode || null,
      customer_relevant: fields.customer_relevant,
      affected_plant_ids: fields.affected_plant_ids,
    });
  };

  const leadItem = change?.impacted_items?.find((i) => i.is_lead);

  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 p-3 space-y-4">
      {/* D1 header fields */}
      <div>
        <div className="font-semibold text-slate-100 mb-2">D1 Fields</div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <label className="flex flex-col gap-0.5">
            <span className="text-slate-400 text-xs">{t('issuer')}</span>
            <input
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
              value={fields.issuer}
              onChange={(e) => setFields((f) => ({ ...f, issuer: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-slate-400 text-xs">{t('car_line')}</span>
            <input
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
              value={fields.car_line}
              onChange={(e) => setFields((f) => ({ ...f, car_line: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-slate-400 text-xs">{t('implementation_mode')}</span>
            <select
              className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
              value={fields.implementation_mode}
              onChange={(e) => setFields((f) => ({ ...f, implementation_mode: e.target.value as D1Fields['implementation_mode'] }))}
            >
              <option value="">—</option>
              <option value="integrated">{t('integrated')}</option>
              <option value="separational">{t('separational')}</option>
            </select>
          </label>
          <div className="flex flex-col gap-1 pt-1">
            {([
              ['is_series', 'is_series'],
              ['cm_internal', 'cm_internal'],
              ['cm_external', 'cm_external'],
              ['customer_relevant', 'customer_relevant'],
            ] as const).map(([key, labelKey]) => (
              <label key={key} className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-sky-500"
                  checked={fields[key]}
                  onChange={(e) => setFields((f) => ({ ...f, [key]: e.target.checked }))}
                />
                {t(labelKey)}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Affected plants */}
      <div>
        <div className="text-xs font-semibold text-slate-300 mb-1">{t('affected_plants')}</div>
        <div className="flex flex-wrap gap-2">
          {allPlants.map((p) => (
            <label key={p.id} className="flex items-center gap-1 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                className="accent-sky-500"
                checked={fields.affected_plant_ids.includes(p.id)}
                onChange={() => togglePlant(p.id)}
              />
              {p.name} ({p.code})
            </label>
          ))}
          {allPlants.length === 0 && <span className="text-slate-500 text-xs">No plants</span>}
        </div>
      </div>

      {/* Impacted items / Leit-Teil */}
      <div>
        <div className="text-xs font-semibold text-slate-300 mb-1">{t('impacted_items')}</div>
        {change?.impacted_items && change.impacted_items.length > 0 ? (
          <ul className="text-xs space-y-0.5">
            {change.impacted_items.map((item) => (
              <li key={item.id} className="flex items-center gap-1.5 text-slate-300">
                <span>Part #{item.part_id}</span>
                {item.is_lead && (
                  <span className="px-1.5 py-0.5 rounded bg-amber-600/30 text-amber-300 text-xs font-medium">
                    {t('lead_part')}
                  </span>
                )}
                {item.impact_note && <span className="text-slate-500">— {item.impact_note}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-slate-500 text-xs">{leadItem ? '' : t('no_lead_set')}</span>
        )}
      </div>

      {/* Save button */}
      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={updateChange.isPending}
          className="px-3 py-1 text-xs rounded bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-50"
        >
          {updateChange.isPending ? t('saving') : t('save')}
        </button>
      </div>

      {/* Gates */}
      <div>
        <div className="font-semibold text-slate-100 mb-2">Final assessment</div>
        <div className="space-y-2">
          {GATES.map((key) => {
            const g = byKey[key];
            const decidedAt = g?.decided_at
              ? new Date(g.decided_at).toLocaleDateString()
              : '—';
            const decidedBy = g?.decided_by != null ? `#${g.decided_by}` : '—';
            return (
              <div key={key} className="text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-slate-200">{t(key)}</span>
                  <span className="flex gap-1">
                    {(['yes', 'no', 'na'] as const).map((d) => (
                      <button
                        key={d}
                        onClick={() => decide.mutate({ key, decision: d })}
                        className={`px-2 py-0.5 rounded text-xs border ${g?.decision === d
                          ? 'bg-sky-600 text-white border-sky-500'
                          : 'bg-slate-900 text-slate-300 border-slate-600'}`}
                      >
                        {d}
                      </button>
                    ))}
                  </span>
                </div>
                {g?.decision && (
                  <div className="text-xs text-slate-500 mt-0.5 pl-1">
                    {t('decided_by')}: {decidedBy} · {t('decided_at')}: {decidedAt}
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
