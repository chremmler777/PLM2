import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import SplitPane from './SplitPane'

const mount = (rightHidden = false) =>
  render(<SplitPane storageKey="k" rightHidden={rightHidden} left={<div>left</div>} right={<div>right</div>} />)
const width = () => screen.getByRole('separator').getAttribute('aria-valuenow')

describe('SplitPane', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('starts at the default width', () => {
    mount()
    expect(width()).toBe('420')
    expect(screen.getByText('left')).toBeTruthy()
    expect(screen.getByText('right')).toBeTruthy()
  })

  it('follows a drag and remembers where it was dropped', () => {
    mount()
    fireEvent.mouseDown(screen.getByRole('separator'), { clientX: 500 })
    fireEvent.mouseMove(window, { clientX: 530 })
    expect(width()).toBe('450')
    fireEvent.mouseUp(window, { clientX: 560 })
    expect(width()).toBe('480')
    expect(localStorage.getItem('k')).toBe('480')
    cleanup()
    mount()
    expect(width()).toBe('480')
  })

  it('never goes below the minimum width', () => {
    mount()
    fireEvent.mouseDown(screen.getByRole('separator'), { clientX: 500 })
    fireEvent.mouseUp(window, { clientX: 0 })
    expect(width()).toBe('280')
  })

  it('moves with the arrow keys', () => {
    mount()
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowRight' })
    expect(width()).toBe('436')
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowLeft' })
    expect(width()).toBe('420')
  })

  it('treats garbage in storage as the default and clamps stored extremes', () => {
    localStorage.setItem('k', 'abc')
    mount()
    expect(width()).toBe('420')
    cleanup()
    localStorage.setItem('k', '99999')
    mount()
    expect(width()).toBe('1600')
    cleanup()
    localStorage.setItem('k', '-5')
    mount()
    expect(width()).toBe('280')
  })

  it('keeps working when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    mount()
    expect(width()).toBe('420')
    fireEvent.mouseDown(screen.getByRole('separator'), { clientX: 500 })
    expect(() => fireEvent.mouseUp(window, { clientX: 560 })).not.toThrow()
    expect(width()).toBe('480')
  })

  it('hides the right pane and the splitter on request', () => {
    mount(true)
    expect(screen.queryByRole('separator')).toBeNull()
    expect(screen.queryByText('right')).toBeNull()
    expect(screen.getByText('left')).toBeTruthy()
  })
})
