import { describe, it, expect } from 'vitest';
import rawVectors from '../../../backend/app/data/forms/expr_vectors.json';
import { evaluate, ExprError } from './expr';

type Vector = { expr: string; scope: Record<string, unknown>; expected?: unknown; error?: boolean };
const vectors = rawVectors as Vector[];

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
