import { describe, it, expect } from 'vitest';
import { defaultPlantId } from './plants';

const PLANTS = [
  { id: 1, name: 'Main Factory', is_active: false },
  { id: 2, name: 'USA Toccoa', is_active: true },
  { id: 3, name: 'Weissenburg', is_active: true },
  { id: 4, name: 'Some Other Plant', is_active: true },
];

describe('defaultPlantId', () => {
  it('returns the project plant when present and active', () => {
    expect(defaultPlantId(PLANTS, 3)).toBe(3);
  });

  it('falls back to USA Toccoa when project plant is absent', () => {
    expect(defaultPlantId(PLANTS, undefined)).toBe(2);
    expect(defaultPlantId(PLANTS, null)).toBe(2);
  });

  it('falls back to USA Toccoa when project plant id does not match any plant', () => {
    expect(defaultPlantId(PLANTS, 999)).toBe(2);
  });

  it('falls back to USA Toccoa when project plant is inactive', () => {
    expect(defaultPlantId(PLANTS, 1)).toBe(2);
  });

  it('never returns an inactive plant even as project plant match', () => {
    const result = defaultPlantId(PLANTS, 1);
    expect(result).not.toBe(1);
  });

  it('falls back to the first active plant when USA Toccoa is absent', () => {
    const noUsa = [
      { id: 1, name: 'Main Factory', is_active: false },
      { id: 3, name: 'Weissenburg', is_active: true },
      { id: 4, name: 'Some Other Plant', is_active: true },
    ];
    expect(defaultPlantId(noUsa, undefined)).toBe(3);
  });

  it('returns null when there are no active plants', () => {
    const allInactive = [{ id: 1, name: 'Main Factory', is_active: false }];
    expect(defaultPlantId(allInactive, undefined)).toBeNull();
  });

  it('returns null for an empty plant list', () => {
    expect(defaultPlantId([], undefined)).toBeNull();
  });

  it('treats missing is_active as active (defensive default)', () => {
    const noFlag = [{ id: 5, name: 'USA Toccoa' }];
    expect(defaultPlantId(noFlag, undefined)).toBe(5);
  });
});
