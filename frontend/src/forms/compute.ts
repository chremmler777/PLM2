import { evaluate } from './expr';
import type { FormDefinitionBody, FormData, Row } from './types';

const safe = (expr: string, scope: Record<string, unknown>) => { try { return evaluate(expr, scope); } catch { return null; } };

export function recompute(body: FormDefinitionBody, data: FormData): FormData {
  const out: FormData = { ...data };
  for (const s of body.sections) {
    if (s.kind === 'fields') {
      const vals: Record<string, unknown> = { ...((data[s.id] as Record<string, unknown>) ?? {}) };
      for (const f of s.fields) if (f.type === 'computed') vals[f.id] = safe(f.expr ?? '', vals);
      out[s.id] = vals;
    } else {
      const rows = (((data[s.id] as Row[]) ?? []).map((r) => ({ ...r })));
      for (const r of rows) for (const c of s.columns) if (c.type === 'computed') r[c.id] = safe(c.expr ?? '', r);
      out[s.id] = rows;
      if (s.footer) out[`${s.id}_footer`] = Object.fromEntries(s.footer.map((f) => [f.label, safe(f.expr, { _rows: rows })]));
    }
  }
  return out;
}
