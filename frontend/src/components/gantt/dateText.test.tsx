import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { formatDateInput, parseDateInput, readDateInput } from './dateText'
import DateInput from './DateInput'

describe('date text (G19: no locale mm/dd)', () => {
  it('formats ISO as d MMM yyyy', () => {
    expect(formatDateInput('2026-10-05')).toBe('5 Oct 2026')
    expect(formatDateInput('')).toBe('')
    expect(formatDateInput('nonsense')).toBe('')
  })
  it('parses dd.mm.yyyy, dd.mm.yy, d.m.yyyy and ISO; rejects the rest', () => {
    expect(parseDateInput('05.10.2026')).toBe('2026-10-05')
    expect(parseDateInput('5.10.26')).toBe('2026-10-05')
    expect(parseDateInput('2026-10-05')).toBe('2026-10-05')
    expect(parseDateInput('31.02.2026')).toBeNull()
    expect(parseDateInput('10/05')).toBeNull()
    expect(parseDateInput('')).toBeNull()
  })
  it('reads month names: 25 Sep 2026, 25 sep 26, 25-Sep-2026, 5 September 2026 (WP1)', () => {
    expect(parseDateInput('25 Sep 2026')).toBe('2026-09-25')
    expect(parseDateInput('25 sep 26')).toBe('2026-09-25')
    expect(parseDateInput('25-Sep-2026')).toBe('2026-09-25')
    expect(parseDateInput('5 September 2026')).toBe('2026-09-05')
    expect(parseDateInput('5 Sept. 2026')).toBe('2026-09-05')
    expect(parseDateInput('31 Feb 2026')).toBeNull()
    expect(parseDateInput('5 Se 2026')).toBeNull()
    expect(parseDateInput('5 Foo 2026')).toBeNull()
  })
  it('reads US order when the month is a name: Sep 25, 2026 and September 25 2026', () => {
    expect(parseDateInput('Sep 25, 2026')).toBe('2026-09-25')
    expect(parseDateInput('September 25 2026')).toBe('2026-09-25')
    expect(parseDateInput('sep 25 26')).toBe('2026-09-25')
    expect(parseDateInput('Sept. 5, 2026')).toBe('2026-09-05')
    expect(parseDateInput('Oct 5th, 2026')).toBe('2026-10-05')
    expect(parseDateInput('Feb 31, 2026')).toBeNull()
    expect(parseDateInput('Foo 25, 2026')).toBeNull()
    expect(parseDateInput('Sep 2026')).toBeNull()
    // Slashes stay refused, month name or not.
    expect(readDateInput('Sep/25/2026').error).toContain('slashes')
    expect(readDateInput('09/25/2026').iso).toBeNull()
  })
  it('two-digit years pivot at 70: 00-69 are 20xx, 70-99 are 19xx (review #8)', () => {
    expect(parseDateInput('01.01.00')).toBe('2000-01-01')
    expect(parseDateInput('01.01.69')).toBe('2069-01-01')
    expect(parseDateInput('01.01.70')).toBe('1970-01-01')
    expect(parseDateInput('31.12.99')).toBe('1999-12-31')
    expect(parseDateInput('05-10-2026')).toBe('2026-10-05')
  })
  it('refuses slashes and out-of-range years with a reason', () => {
    expect(readDateInput('01/02/2026')).toEqual({ iso: null, error: expect.stringContaining('25 Sep 2026') })
    expect(readDateInput('01.01.1899')).toEqual({ iso: null, error: 'The year must be between 1900 and 2200' })
    expect(readDateInput('01.01.2201').iso).toBeNull()
    expect(readDateInput('1899-12-31').error).toContain('1900')
    expect(readDateInput('32.01.2026').error).toContain('Not a date')
    expect(readDateInput('')).toEqual({ iso: null, error: null })
  })
})

describe('DateInput', () => {
  afterEach(cleanup)
  it('commits a typed date on blur and reverts nonsense', () => {
    const onChange = vi.fn()
    render(<DateInput aria-label="Start" value="2026-10-05" onChange={onChange} />)
    const input = screen.getByLabelText('Start') as HTMLInputElement
    expect(input.value).toBe('5 Oct 2026')
    fireEvent.change(input, { target: { value: '07.10.2026' } })
    fireEvent.blur(input)
    expect(onChange).toHaveBeenCalledWith('2026-10-07')
    fireEvent.change(input, { target: { value: 'soon' } })
    fireEvent.blur(input)
    expect(input.value).toBe('5 Oct 2026')
  })
  it('picks a day from the calendar popover and respects max', () => {
    const onChange = vi.fn()
    render(<DateInput aria-label="Actual" value="2026-10-05" max="2026-10-10" onChange={onChange} />)
    fireEvent.click(screen.getByLabelText('Open calendar'))
    expect(screen.getByTestId('date-popover')).toBeTruthy()
    expect((screen.getByLabelText('20 Oct 2026') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByLabelText('8 Oct 2026'))
    expect(onChange).toHaveBeenCalledWith('2026-10-08')
  })
})

describe('DateInput popover and messages (review #5, #8)', () => {
  afterEach(cleanup)
  const mount = (over: Partial<React.ComponentProps<typeof DateInput>> = {}) => {
    const onChange = vi.fn()
    render(<DateInput aria-label="Start" value="2026-10-05" onChange={onChange} {...over} />)
    return { onChange, input: screen.getByLabelText('Start') as HTMLInputElement }
  }

  it('the calendar button is focusable and the popover lives in a portal on the body', () => {
    mount()
    const btn = screen.getByLabelText('Open calendar')
    expect(btn.getAttribute('tabindex')).toBeNull()
    fireEvent.click(btn)
    expect(screen.getByTestId('date-popover').parentElement).toBe(document.body)
  })

  it('portals the popover into an open <dialog>, not under a modal top layer on the body', () => {
    render(
      <dialog open data-testid="dlg">
        <DateInput aria-label="Due" value="2026-10-05" onChange={vi.fn()} />
      </dialog>,
    )
    fireEvent.click(screen.getByLabelText('Open calendar'))
    const popover = screen.getByTestId('date-popover')
    expect(popover.parentElement).toBe(screen.getByTestId('dlg'))
    // A day in the dialog-hosted calendar still commits.
    fireEvent.click(screen.getByLabelText('7 Oct 2026'))
    expect(screen.queryByTestId('date-popover')).toBeNull()
  })

  it('offsets the popover by a dialog that is the fixed containing block (transform)', () => {
    render(
      <dialog open data-testid="dlg" style={{ transform: 'translate(-50%, -50%)' }}>
        <DateInput aria-label="Due" value="2026-10-05" onChange={vi.fn()} />
      </dialog>,
    )
    const dlg = screen.getByTestId('dlg')
    dlg.getBoundingClientRect = () => ({ left: 100, top: 50, right: 500, bottom: 450, width: 400, height: 400, x: 100, y: 50, toJSON: () => ({}) })
    fireEvent.click(screen.getByLabelText('Open calendar'))
    const popover = screen.getByTestId('date-popover')
    expect(popover.parentElement).toBe(dlg)
    // jsdom lays the field out at 0,0: the viewport position is clamped to 4,4.
    expect(popover.style.left).toBe('-96px')
    expect(popover.style.top).toBe('-46px')
  })

  it('Escape with the popover open closes only the popover', () => {
    const outer = vi.fn()
    const onChange = vi.fn()
    render(<div onKeyDown={outer}><DateInput aria-label="Start" value="2026-10-05" onChange={onChange} /></div>)
    const input = screen.getByLabelText('Start')
    fireEvent.keyDown(input, { key: 'ArrowDown', altKey: true })
    expect(screen.getByTestId('date-popover')).toBeTruthy()
    const ev = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    act(() => { input.dispatchEvent(ev) })
    expect(ev.defaultPrevented).toBe(true)
    expect(screen.queryByTestId('date-popover')).toBeNull()
    expect(outer).toHaveBeenCalledTimes(1) // only the Alt+Down; Escape stayed inside
    // from inside the popover too
    fireEvent.keyDown(input, { key: 'ArrowDown', altKey: true })
    fireEvent.keyDown(screen.getByLabelText('5 Oct 2026'), { key: 'Escape' })
    expect(screen.queryByTestId('date-popover')).toBeNull()
    expect(outer).toHaveBeenCalledTimes(2)
  })

  it('arrow keys move the day, PageDown the month, Enter picks', async () => {
    const { onChange } = mount()
    fireEvent.keyDown(screen.getByLabelText('Start'), { key: 'ArrowDown', altKey: true })
    const day = (t: string) => screen.getByLabelText(t)
    await new Promise((r) => requestAnimationFrame(r))
    expect(document.activeElement).toBe(day('5 Oct 2026'))
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowRight' })
    expect(day('6 Oct 2026').getAttribute('tabindex')).toBe('0')
    fireEvent.keyDown(day('6 Oct 2026'), { key: 'ArrowDown' })
    expect(day('13 Oct 2026').getAttribute('tabindex')).toBe('0')
    fireEvent.keyDown(day('13 Oct 2026'), { key: 'PageDown' })
    expect(screen.getByTestId('date-popover').textContent).toContain('Nov 2026')
    fireEvent.click(day('13 Nov 2026'))
    expect(onChange).toHaveBeenCalledWith('2026-11-13')
  })

  it('a mouse click on the calendar button keeps focus in the field: Escape and arrows work from there', async () => {
    mount()
    const input = screen.getByLabelText('Start')
    fireEvent.click(screen.getByLabelText('Open calendar'), { detail: 1 })
    expect(document.activeElement).toBe(input)
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(screen.getByLabelText('5 Oct 2026'))
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(screen.queryByTestId('date-popover')).toBeNull()
    expect(document.activeElement).toBe(input)
  })

  it('Tab away from the calendar closes it', () => {
    render(<><DateInput aria-label="Start" value="2026-10-05" onChange={vi.fn()} /><button type="button">next</button></>)
    fireEvent.click(screen.getByLabelText('Open calendar'))
    fireEvent.blur(screen.getByLabelText('5 Oct 2026'), { relatedTarget: screen.getByText('next') })
    expect(screen.queryByTestId('date-popover')).toBeNull()
  })

  it('Tab to the calendar button, then a click away, commits the typed date (whole-control blur)', () => {
    const onChange = vi.fn()
    const onBlur = vi.fn()
    render(<><DateInput aria-label="Start" value="2026-10-05" onChange={onChange} onBlur={onBlur} /><button type="button">elsewhere</button></>)
    const input = screen.getByLabelText('Start') as HTMLInputElement
    const btn = screen.getByLabelText('Open calendar')
    fireEvent.change(input, { target: { value: '09.10.2026' } })
    // Tab: focus moves from the field to the calendar button, still inside
    fireEvent.blur(input, { relatedTarget: btn })
    expect(onChange).not.toHaveBeenCalled()
    expect(onBlur).not.toHaveBeenCalled()
    // click away: the button loses focus to nothing focusable
    fireEvent.blur(btn, { relatedTarget: null })
    expect(onChange).toHaveBeenCalledWith('2026-10-09')
    expect(onBlur).toHaveBeenCalledTimes(1)
    expect(input.value).toBe('9 Oct 2026')
  })

  it('Tab from the calendar button to the next field commits too', () => {
    const onChange = vi.fn()
    render(<><DateInput aria-label="Start" value="2026-10-05" onChange={onChange} /><button type="button">next</button></>)
    const input = screen.getByLabelText('Start')
    fireEvent.change(input, { target: { value: '12.10.2026' } })
    fireEvent.blur(input, { relatedTarget: screen.getByLabelText('Open calendar') })
    fireEvent.blur(screen.getByLabelText('Open calendar'), { relatedTarget: screen.getByText('next') })
    expect(onChange).toHaveBeenCalledWith('2026-10-12')
  })

  it('a slash date or a year out of range keeps the value and says why', () => {
    const { input, onChange } = mount()
    fireEvent.change(input, { target: { value: '01/02/2026' } })
    expect(screen.getByTestId('date-input-error').textContent).toContain('25 Sep 2026')
    fireEvent.blur(input)
    expect(input.value).toBe('5 Oct 2026')
    expect(screen.getByTestId('date-input-error').textContent).toContain('kept 5 Oct 2026')
    fireEvent.change(input, { target: { value: '01.01.2300' } })
    fireEvent.blur(input)
    expect(screen.getByTestId('date-input-error').textContent).toContain('between 1900 and 2200')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('echoes the date it read while the text is in another form, and not once it is shown as such', () => {
    const { input } = mount()
    expect(screen.queryByTestId('date-input-echo')).toBeNull()
    fireEvent.change(input, { target: { value: '2026-09-25' } })
    expect(screen.getByTestId('date-input-echo').textContent).toBe('= 25 Sep 2026')
    fireEvent.change(input, { target: { value: '25 Sep 2026' } })
    expect(screen.queryByTestId('date-input-echo')).toBeNull()
    fireEvent.change(input, { target: { value: '25/09/2026' } })
    expect(screen.queryByTestId('date-input-echo')).toBeNull()
    expect(screen.getByTestId('date-input-error')).toBeTruthy()
  })

  it('a required field refuses to be cleared', () => {
    const { input, onChange } = mount({ required: true })
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByTestId('date-input-error').textContent).toBe('Start is required')
  })
})
