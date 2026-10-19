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

describe('D2 wording (Project Management owns the process, R37)', () => {
  // Sales is the change's commercial contact, not its process owner: no
  // label may say Sales owns it, names a "Sales owner", or makes the
  // lead's risk escalation Sales' (DECIDED BY CHRISTOPH 2026-10-19, D2).
  const STALE = /Sales owns|Sales owner|Sales escalation|Vertriebsverantwortlich|Eskalation durch den Vertrieb/i
  it('no label says Sales owns the process', () => {
    const bad = Object.entries(cmLabels).flatMap(([k, v]) =>
      (['de', 'en'] as const).filter((l) => STALE.test(v[l])).map((l) => `${k}.${l}: ${v[l]}`))
    expect(bad).toEqual([])
  })
  it('negative: the guard catches the old wording', () => {
    expect(STALE.test('At-risk flagged - Sales escalation pending')).toBe(true)
    expect(STALE.test('the Sales contact sends the offer')).toBe(false)
  })
})

