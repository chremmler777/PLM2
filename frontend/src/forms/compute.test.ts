import { describe, it, expect } from 'vitest';
import { recompute } from './compute';
import type { FormDefinitionBody, FormData } from './types';

const MINI: FormDefinitionBody = {
  key: 'mini', version: 1, title: 'Mini', implements: null, cardinality: 'single',
  gate_items: false, sep_items: ['K0/RG1:2'], signatures: [], required_for_submit: ['header.name', 'rows'],
  sections: [
    { id: 'header', title: 'H', kind: 'fields', fields: [
      { id: 'name', label: 'Name', type: 'text', prefill: 'project.name' },
      { id: 'n', label: 'N', type: 'number' },
      { id: 'double', label: 'Double', type: 'computed', expr: 'n * 2' },
    ] },
    { id: 'rows', title: 'Rows', kind: 'table', min_rows: 1, columns: [
      { id: 'q', label: 'Q', type: 'number' },
      { id: 'p', label: 'P', type: 'number' },
      { id: 'r', label: 'R', type: 'computed', expr: 'q * p' },
      { id: 'status', label: 'Status', type: 'choice', options: ['open', 'done'] },
    ], footer: [{ label: 'Open', expr: "count(status == 'open')" }] },
  ],
};

describe('recompute', () => {
  it('computes fields, table columns and footer', () => {
    const data: FormData = {
      header: { name: 'x', n: 2 },
      rows: [{ q: 0.5, p: 1, status: 'open' }, { q: 1, p: 1, status: 'done' }],
    };
    const out = recompute(MINI, data);
    expect((out.header as Record<string, unknown>).double).toBe(4);
    expect((out.rows as Record<string, unknown>[]).map((r) => r.r)).toEqual([0.5, 1]);
    expect(out.rows_footer).toEqual({ Open: 1 });
  });

  it('does not crash on empty data', () => {
    expect(() => recompute(MINI, {})).not.toThrow();
  });
});
