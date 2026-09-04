import { recompute } from './compute';
import type { FormDefinitionBody, FormData, FieldDef, Row, TableSection } from './types';

interface UserOption { id: number; name: string }
interface Props { body: FormDefinitionBody; data: FormData; onChange: (next: FormData) => void; readOnly?: boolean; users: UserOption[] }

const INPUT = 'w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-100 disabled:opacity-60';

function display(f: FieldDef, v: unknown, users: UserOption[]): string {
  if (v === null || v === undefined || v === '') return '';
  if (f.type === 'checkbox') return v ? 'yes' : 'no';
  if (f.type === 'user') return users.find((u) => u.id === Number(v))?.name ?? String(v);
  if (f.type === 'multichoice' && Array.isArray(v)) return v.join(', ');
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\.?0+$/, '');
  return String(v);
}

function FieldInput({ f, value, onChange, readOnly, users, id }:
  { f: FieldDef; value: unknown; onChange: (v: unknown) => void; readOnly: boolean; users: UserOption[]; id: string }) {
  const ro = readOnly || f.readonly || f.type === 'computed';
  if (ro) return <div id={id} className="text-sm text-slate-200 min-h-[1.75rem] py-1">{display(f, value, users)}</div>;
  switch (f.type) {
    case 'multiline': return <textarea id={id} className={INPUT} rows={2} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />;
    case 'number': return <input id={id} type="number" className={INPUT} min={f.min} max={f.max} step={f.step ?? 'any'}
      value={value === null || value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />;
    case 'date': return <input id={id} type="date" className={INPUT} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)} />;
    case 'checkbox': return <input id={id} type="checkbox" className="h-4 w-4 mt-2" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />;
    case 'choice': return (
      <select id={id} className={INPUT} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">—</option>{f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    case 'multichoice': return (
      <select id={id} multiple className={INPUT} value={(value as string[]) ?? []}
        onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((o) => o.value))}>
        {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    case 'user': return (
      <select id={id} className={INPUT} value={value === null || value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">unassigned</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
      </select>);
    default: return <input id={id} type="text" className={INPUT} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />;
  }
}

function TableEditor({ s, rows, footer, onRows, readOnly, users }:
  { s: TableSection; rows: Row[]; footer: Record<string, unknown> | undefined; onRows: (rows: Row[]) => void; readOnly: boolean; users: UserOption[] }) {
  const setCell = (i: number, id: string, v: unknown) => onRows(rows.map((r, j) => (j === i ? { ...r, [id]: v } : r)));
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead><tr className="text-slate-400">
          <th className="px-1 text-left w-6">#</th>
          {s.columns.map((c) => <th key={c.id} className="px-1 text-left font-medium" style={{ minWidth: `${(c.width ?? 1) * 6}rem` }}>{c.label}</th>)}
          {!readOnly && <th className="w-8" />}
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-700/60 align-top">
              <td className="px-1 py-1 text-slate-500">{i + 1}</td>
              {s.columns.map((c) => <td key={c.id} className="px-1 py-1">
                <FieldInput id={`${s.id}-${i}-${c.id}`} f={c} value={r[c.id]} onChange={(v) => setCell(i, c.id, v)} readOnly={readOnly} users={users} />
              </td>)}
              {!readOnly && <td className="px-1 py-1"><button type="button" aria-label="remove row" className="text-slate-500 hover:text-red-400" onClick={() => onRows(rows.filter((_, j) => j !== i))}>✕</button></td>}
            </tr>))}
        </tbody>
      </table>
      <div className="flex items-center gap-3 mt-2">
        {!readOnly && <button type="button" className="text-xs px-2 py-1 rounded border border-slate-600 text-slate-300 hover:border-slate-400" onClick={() => onRows([...rows, {}])}>+ Add row</button>}
        {footer && Object.entries(footer).map(([k, v]) => <span key={k} className="text-xs px-2 py-0.5 rounded bg-slate-700/60 text-slate-300">{k}: {display({ id: k, label: k, type: 'text' }, v, users)}</span>)}
      </div>
    </div>
  );
}

export default function FormRenderer({ body, data, onChange, readOnly = false, users }: Props) {
  const computed = recompute(body, data);
  const update = (next: FormData) => onChange(recompute(body, next));
  return (
    <div className="space-y-5">
      {body.sections.map((s) => (
        <section key={s.id}>
          <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{s.title}</h4>
          {s.kind === 'fields' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
              {s.fields.map((f) => {
                const id = `${s.id}-${f.id}`;
                const vals = (computed[s.id] as Record<string, unknown>) ?? {};
                return (
                  <div key={f.id}>
                    <label htmlFor={id} className="block text-xs text-slate-400 mb-0.5">{f.label}{f.required && ' *'}</label>
                    <FieldInput id={id} f={f} value={vals[f.id]} readOnly={readOnly} users={users}
                      onChange={(v) => update({ ...computed, [s.id]: { ...vals, [f.id]: v } })} />
                    {f.help && <p className="text-[11px] text-slate-500 mt-0.5">{f.help}</p>}
                  </div>);
              })}
            </div>
          ) : (
            <TableEditor s={s} rows={(computed[s.id] as Row[]) ?? []} footer={computed[`${s.id}_footer`] as Record<string, unknown> | undefined}
              onRows={(rows) => update({ ...computed, [s.id]: rows })} readOnly={readOnly} users={users} />
          )}
        </section>
      ))}
    </div>
  );
}
