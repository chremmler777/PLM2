/**
 * Every "Next step" item the backend can add (ChangeService next_step:
 * add("<key>", ...)) has its label here, so the cockpit never shows a raw
 * 'next.item.<key>' (R5/R37).
 */
import { describe, expect, it } from 'vitest'
import { t } from './cmLabels'
import source from '../../../backend/app/services/change_service.py?raw'

describe('next-step item labels', () => {
  it('every backend item key has an en label', () => {
    const keys = [...new Set([...source.matchAll(/\badd\(\s*"([a-z0-9_]+)"/g)].map((m) => m[1]))]
    expect(keys.length).toBeGreaterThan(20)
    const missing = keys.filter((k) => t(`next.item.${k}`) === `next.item.${k}`)
    expect(missing).toEqual([])
  })

  it('names the L6 rules in words', () => {
    expect(t('next.item.scope_change')).toBe('Scope change covered by an offer')
    expect(t('next.item.price_drop')).toContain('lower price')
  })
})
