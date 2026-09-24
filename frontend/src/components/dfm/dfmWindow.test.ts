import { describe, it, expect, vi, afterEach } from 'vitest'
import { toast } from 'sonner'
import { dfmWindowUrl, openDfmWindow } from './dfmWindow'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe('DFM pop-out window', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('builds the route with an optional topic', () => {
    expect(dfmWindowUrl(7, null)).toBe(`${import.meta.env.BASE_URL}parts/7/dfm`)
    expect(dfmWindowUrl(7, 3)).toBe(`${import.meta.env.BASE_URL}parts/7/dfm?topic=3`)
  })

  it('opens one named window per tool, so a second click reuses it', () => {
    const focus = vi.fn()
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus } as unknown as Window)
    expect(openDfmWindow(7, 3)).toBe(true)
    expect(open).toHaveBeenCalledWith(dfmWindowUrl(7, 3), 'plm2-dfm-7', expect.stringContaining('popup'))
    expect(focus).toHaveBeenCalled()
  })

  it('says so when the browser blocks the window', () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    expect(openDfmWindow(7, null)).toBe(false)
    expect(toast.error).toHaveBeenCalledWith('The browser blocked the new window')
  })
})
