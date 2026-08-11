import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import ActsAsSwitch from './ActsAsSwitch'
import { setActsAsDepartmentId, getActsAsDepartmentId } from '../../lib/actsAs'
import { t } from '../../i18n/cmLabels'

vi.mock('../../hooks/queries/useWorkflows', () => ({
  useDepartments: () => ({
    data: [
      { id: 4, name: 'Tool Engineer', flow_type: 'action', is_active: true, sort_order: 1 },
      { id: 8, name: 'Logistics', flow_type: 'action', is_active: false, sort_order: 2 },
    ],
  }),
}))

const reload = vi.fn()
beforeEach(() => {
  sessionStorage.clear()
  reload.mockClear()
  Object.defineProperty(window, 'location', {
    configurable: true, value: { ...window.location, reload },
  })
})
afterEach(cleanup)

describe('ActsAsSwitch', () => {
  it('offers only active departments and stores the pick', () => {
    render(<ActsAsSwitch />)
    const select = screen.getByTestId('acts-as-select') as HTMLSelectElement
    // "Myself" plus the one active department; the retired one is not offered.
    expect(select.querySelectorAll('option')).toHaveLength(2)
    expect(screen.queryByText('Logistics')).toBeNull()
    fireEvent.change(select, { target: { value: '4' } })
    expect(getActsAsDepartmentId()).toBe(4)
    expect(reload).toHaveBeenCalled()
  })

  it('shows what it is acting as and clears in one click', () => {
    setActsAsDepartmentId(4)
    render(<ActsAsSwitch />)
    expect(screen.getByTestId('acts-as-banner').textContent).toContain('Tool Engineer')
    expect(screen.getByTestId('acts-as-banner').textContent).toContain(t('actsAs.acting'))
    fireEvent.click(screen.getByTestId('acts-as-clear'))
    expect(getActsAsDepartmentId()).toBeNull()
    expect(reload).toHaveBeenCalled()
  })

  it('says nothing on the collapsed rail while the admin is themselves', () => {
    const { container } = render(<ActsAsSwitch collapsed />)
    expect(container.firstChild).toBeNull()
    cleanup()
    setActsAsDepartmentId(4)
    render(<ActsAsSwitch collapsed />)
    expect(screen.getByTestId('acts-as-clear')).toBeDefined()
  })
})
