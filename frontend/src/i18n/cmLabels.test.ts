import { describe, it, expect } from 'vitest';
import { t, cmLabels } from './cmLabels';

describe('cmLabels', () => {
  it('returns English label by default', () => {
    expect(t('one_time')).toBe('One-time cost');
  });

  it('returns German label when lang=de', () => {
    expect(t('one_time', 'de')).toBe('Einmal-Aufwand');
  });

  it('falls back to key for unknown keys', () => {
    expect(t('unknown_key')).toBe('unknown_key');
    expect(t('unknown_key', 'de')).toBe('unknown_key');
  });

  it('covers all gate keys', () => {
    for (const key of ['feasibility', 'budget', 'release']) {
      expect(cmLabels[key]).toBeDefined();
      expect(cmLabels[key].en).toBeTruthy();
      expect(cmLabels[key].de).toBeTruthy();
    }
  });

  it('covers all cost-kind keys', () => {
    for (const key of ['one_time', 'lifecycle']) {
      expect(t(key, 'en')).not.toBe(key);
      expect(t(key, 'de')).not.toBe(key);
    }
  });
});
