import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { evaluate, ExprError } from './expr';

const vectors = JSON.parse(readFileSync(resolve(__dirname, '../../../backend/app/data/forms/expr_vectors.json'), 'utf8')) as
  { expr: string; scope: Record<string, unknown>; expected?: unknown; error?: boolean }[];

describe('expr vectors', () => {
  for (const v of vectors) {
    it(v.expr, () => {
      if (v.error) expect(() => evaluate(v.expr, v.scope)).toThrow(ExprError);
      else if (typeof v.expected === 'number') expect(evaluate(v.expr, v.scope)).toBeCloseTo(v.expected, 6);
      else expect(evaluate(v.expr, v.scope)).toEqual(v.expected);
    });
  }
  it('today is ISO', () => expect(String(evaluate('today()', {}))).toHaveLength(10));
});
