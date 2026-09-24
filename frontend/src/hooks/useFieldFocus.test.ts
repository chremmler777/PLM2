import { describe, it, expect, vi, afterEach } from 'vitest'
import { FOCUS_HIGHLIGHT, focusField } from './useFieldFocus'

describe('focusField', () => {
  afterEach(() => { document.body.innerHTML = ''; vi.useRealTimers() })

  it('rings the field, focuses its control (not the marker) and removes the ring later', () => {
    vi.useFakeTimers()
    document.body.innerHTML = `<div data-field-key="tool.cavities"><button data-note-marker="">m</button><button id="edit">4</button></div>`
    const el = document.querySelector<HTMLElement>('[data-field-key="tool.cavities"]')!
    el.scrollIntoView = vi.fn()
    expect(focusField('tool.cavities')).toBe(true)
    expect(el.classList.contains(FOCUS_HIGHLIGHT[0])).toBe(true)
    expect(document.activeElement?.id).toBe('edit')
    vi.advanceTimersByTime(3000)
    expect(el.classList.contains(FOCUS_HIGHLIGHT[0])).toBe(false)
  })

  it('ignores unknown and malformed keys', () => {
    document.body.innerHTML = `<div data-field-key="part.name"></div>`
    expect(focusField('part.material')).toBe(false)
    expect(focusField('x"] , body')).toBe(false)
  })
})
