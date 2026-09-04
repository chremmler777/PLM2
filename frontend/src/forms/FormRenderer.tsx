import { recompute } from './compute';
import type { FormDefinitionBody, FormData, FieldDef, Row, TableSection } from './types';

interface UserOption { id: number; name: string }
interface Props { body: FormDefinitionBody; data: FormData; onChange: (next: FormData) => void; readOnly?: boolean; users: UserOption[] }

// Matches the app's input vocabulary (see components/changes/*): rounded-lg, slate-900 well, slate-700 hairline.
const INPUT = 'w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 ' +
  'hover:border-slate-600 disabled:opacity-60 transition-colors duration-150';
const CELL_INPUT = 'w-full rounded-md bg-slate-900 border border-slate-700/80 px-2 py-1.5 text-sm text-slate-100 ' +
  'hover:border-slate-600 transition-colors duration-150';
const NUMERIC_TYPES = new Set(['number', 'computed']);

function display(f: FieldDef, v: unknown, users: UserOption[]): string {
  if (v === null || v === undefined || v === '') return '';
  if (f.type === 'checkbox') return v ? 'yes' : 'no';
  if (f.type === 'user') return users.find((u) => u.id === Number(v))?.name ?? String(v);
  if (f.type === 'multichoice' && Array.isArray(v)) return v.join(', ');
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\.?0+$/, '');
  return String(v);
}

/** Static value: computed results, read-only fields and submitted forms. */
function ReadOnlyValue({ f, value, users, id, cell }:
  { f: FieldDef; value: unknown; users: UserOption[]; id: string; cell: boolean }) {
  const text = display(f, value, users);
  const empty = text === '';
  const computed = f.type === 'computed';
  const base = cell ? 'min-h-[2.125rem] px-2 py-1.5 rounded-md' : 'min-h-[2.375rem] px-3 py-2 rounded-lg';
  const tone = empty ? 'text-slate-600' : computed ? 'font-mono text-sky-200' : 'text-slate-100';
  return (
    <div id={id} className={`${base} ${tone} text-sm bg-slate-800/40 border border-transparent tabular-nums`}>
      {empty ? '—' : text}
    </div>
  );
}

function FieldInput({ f, value, onChange, readOnly, users, id, cell = false }:
  { f: FieldDef; value: unknown; onChange: (v: unknown) => void; readOnly: boolean; users: UserOption[]; id: string; cell?: boolean }) {
  const ro = readOnly || f.readonly || f.type === 'computed';
  if (ro) return <ReadOnlyValue f={f} value={value} users={users} id={id} cell={cell} />;
  const cls = cell ? CELL_INPUT : INPUT;
  switch (f.type) {
    case 'multiline': return <textarea id={id} className={`${cls} min-h-[2.375rem] resize-y leading-snug`} rows={cell ? 1 : 3}
      value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />;
    case 'number': return <input id={id} type="number" inputMode="decimal" className={`${cls} font-mono tabular-nums`} min={f.min} max={f.max} step={f.step ?? 'any'}
      value={value === null || value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />;
    case 'date': return <input id={id} type="date" className={cls} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)} />;
    case 'checkbox': return (
      <div className={cell ? 'flex items-center h-[2.125rem]' : 'flex items-center h-[2.375rem]'}>
        <input id={id} type="checkbox" className="h-4 w-4 rounded border-slate-600 bg-slate-900 accent-sky-500 cursor-pointer"
          checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
      </div>);
    case 'choice': return (
      <select id={id} className={cls} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">—</option>{f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    case 'multichoice': return (
      <select id={id} multiple className={`${cls} min-h-[5rem]`} value={(value as string[]) ?? []}
        onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((o) => o.value))}>
        {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    case 'user': return (
      <select id={id} className={cls} value={value === null || value === undefined ? '' : String(value)} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">unassigned</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
      </select>);
    default: return <input id={id} type="text" className={cls} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value)} />;
  }
}

const colWidth = (c: FieldDef) => {
  if (c.width) return `${c.width * 7}rem`;
  if (NUMERIC_TYPES.has(c.type) || c.type === 'checkbox') return '5rem';
  if (c.type === 'date' || c.type === 'choice') return '8.5rem';
  return '10rem';
};

function TableEditor({ s, rows, footer, onRows, readOnly, users }:
  { s: TableSection; rows: Row[]; footer: Record<string, unknown> | undefined; onRows: (rows: Row[]) => void; readOnly: boolean; users: UserOption[] }) {
  const setCell = (i: number, id: string, v: unknown) => onRows(rows.map((r, j) => (j === i ? { ...r, [id]: v } : r)));
  const explained = s.columns.filter((c) => c.help);
  const span = s.columns.length + 1 + (readOnly ? 0 : 1);
  return (
    <div>
      <div className="overflow-x-auto -mx-4 px-4 pb-1">
        <table className="min-w-full text-sm border-separate border-spacing-0">
          <thead>
            <tr>
              <th className="sticky left-0 z-[1] bg-slate-800 px-2 pb-2 text-left text-[11px] font-medium uppercase tracking-wider text-slate-500 w-8">#</th>
              {s.columns.map((c) => (
                <th key={c.id} className="px-2 pb-2 text-left text-[11px] font-medium uppercase tracking-wider text-slate-400 whitespace-nowrap align-bottom"
                  style={{ minWidth: colWidth(c) }}>
                  {c.help
                    ? <abbr title={c.help} className="cursor-help no-underline border-b border-dotted border-slate-500">{c.label}</abbr>
                    : c.label}
                </th>))}
              {!readOnly && <th className="w-9 pb-2" />}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={span} className="rounded-lg border border-dashed border-slate-700 px-3 py-4 text-center text-sm text-slate-500">
                  {readOnly ? 'No entries.' : 'No entries yet. Add the first row below.'}
                </td>
              </tr>)}
            {rows.map((r, i) => (
              <tr key={i} className="group align-top">
                <td className="sticky left-0 z-[1] bg-slate-800 px-2 py-1 font-mono text-xs text-slate-500 leading-[2.125rem]">{i + 1}</td>
                {s.columns.map((c) => <td key={c.id} className="px-1 py-1">
                  <FieldInput id={`${s.id}-${i}-${c.id}`} f={c} value={r[c.id]} onChange={(v) => setCell(i, c.id, v)} readOnly={readOnly} users={users} cell />
                </td>)}
                {!readOnly && (
                  <td className="px-1 py-1">
                    <button type="button" aria-label="remove row" title="Remove row"
                      className="h-[2.125rem] w-8 rounded-md text-slate-500 opacity-40 group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-300 transition-all duration-150"
                      onClick={() => onRows(rows.filter((_, j) => j !== i))}>
                      <svg viewBox="0 0 16 16" className="mx-auto h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>
                    </button>
                  </td>)}
              </tr>))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!readOnly && (
          <button type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700/60 hover:border-slate-500 active:scale-[0.98] transition-all duration-150"
            onClick={() => onRows([...rows, {}])}>
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"><path d="M8 3v10M3 8h10" /></svg>
            Add row
          </button>)}
        {footer && Object.entries(footer).map(([k, v]) => (
          <span key={k} className="inline-flex items-baseline gap-1.5 rounded-lg bg-slate-900/60 border border-slate-700/70 px-2.5 py-1 text-xs text-slate-400">
            {k}
            <span className="font-mono text-sm text-slate-100 tabular-nums">{display({ id: k, label: k, type: 'text' }, v, users) || '—'}</span>
          </span>))}
      </div>
      {explained.length > 0 && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          {explained.map((c) => (
            <span key={c.id} className="inline-block mr-3">{`${c.label} = ${c.help}`}</span>))}
        </p>)}
    </div>
  );
}

export default function FormRenderer({ body, data, onChange, readOnly = false, users }: Props) {
  const computed = recompute(body, data);
  const update = (next: FormData) => onChange(recompute(body, next));
  return (
    <div className="space-y-4">
      {body.sections.map((s, idx) => (
        <section key={s.id} className="rounded-lg border border-slate-700/70 bg-slate-800 p-4 shadow-panel">
          <header className="mb-3 flex items-baseline gap-2">
            <span className="font-mono text-[11px] text-slate-600">{String(idx + 1).padStart(2, '0')}</span>
            <h4 className="text-sm font-semibold tracking-tight text-slate-100">{s.title}</h4>
            {s.kind === 'table' && (
              <span className="ml-auto font-mono text-[11px] text-slate-500 tabular-nums">
                {((computed[s.id] as Row[]) ?? []).length} {((computed[s.id] as Row[]) ?? []).length === 1 ? 'row' : 'rows'}
              </span>)}
          </header>
          {s.kind === 'fields' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5 gap-y-3.5">
              {s.fields.map((f) => {
                const id = `${s.id}-${f.id}`;
                const vals = (computed[s.id] as Record<string, unknown>) ?? {};
                const wide = f.type === 'multiline';
                return (
                  <div key={f.id} className={wide ? 'md:col-span-2' : undefined}>
                    <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-400">
                      {f.label}{f.required && <span className="ml-0.5 text-sky-400">*</span>}
                    </label>
                    <FieldInput id={id} f={f} value={vals[f.id]} readOnly={readOnly} users={users}
                      onChange={(v) => update({ ...computed, [s.id]: { ...vals, [f.id]: v } })} />
                    {f.help && <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{f.help}</p>}
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
