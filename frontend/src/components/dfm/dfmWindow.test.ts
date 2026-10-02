import { describe, it, expect, vi, afterEach } from 'vitest'
import { toast } from 'sonner'
import { dfmWindowUrl, openDfmWindow } from './dfmWindow'
import { projectScope, toolScope } from '../../api/dfm'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

describe('DFM pop-out window', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('builds the route with an optional topic', () => {
    expect(dfmWindowUrl(toolScope(7), null)).toBe(`${import.meta.env.BASE_URL}parts/7/dfm`)
    expect(dfmWindowUrl(toolScope(7), 3)).toBe(`${import.meta.env.BASE_URL}parts/7/dfm?topic=3`)
  })

  it('builds the project route for the general tooling DFM', () => {
    expect(dfmWindowUrl(projectScope(35), null)).toBe(`${import.meta.env.BASE_URL}projects/35/dfm`)
    expect(dfmWindowUrl(projectScope(35), 4)).toBe(`${import.meta.env.BASE_URL}projects/35/dfm?topic=4`)
  })

  it('opens one named window per tool, so a second click reuses it', () => {
    const focus = vi.fn()
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus } as unknown as Window)
    expect(openDfmWindow(toolScope(7), 3)).toBe(true)
    expect(open).toHaveBeenCalledWith(dfmWindowUrl(toolScope(7), 3), 'plm2-dfm-7', expect.stringContaining('popup'))
    expect(focus).toHaveBeenCalled()
  })

  it('names the project window apart from a tool window with the same id', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() } as unknown as Window)
    openDfmWindow(projectScope(7), null)
    expect(open).toHaveBeenCalledWith(dfmWindowUrl(projectScope(7), null), 'plm2-dfm-project-7', expect.stringContaining('popup'))
  })

  it('says so when the browser blocks the window', () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    expect(openDfmWindow(toolScope(7), null)).toBe(false)
    expect(toast.error).toHaveBeenCalledWith('The browser blocked the new window')
  })
})
