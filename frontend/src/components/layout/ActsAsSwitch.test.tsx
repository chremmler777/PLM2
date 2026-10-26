import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render as rtlRender, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ActsAsSwitch, { ViewingAsBanner } from './ActsAsSwitch'
import { setActsAsDepartmentId, getActsAsDepartmentId, getActsAsUserId, setActsAsUserId } from '../../lib/actsAs'
import { attachActsAs } from '../../api/client'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', async (orig) => {
  const real = await orig<typeof import('../../api/client')>()
  return { ...real, default: clientMocks }
})
const render = (ui: React.ReactElement) => rtlRender(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)
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
  clientMocks.get.mockResolvedValue({ data: { departments: [], people: [{ id: 21, name: 'Russ Addison' }] } })
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

  it('offers people too; picking one sends X-Acts-As-User instead of the department', async () => {
    setActsAsDepartmentId(4)
    render(<ActsAsSwitch />)
    const sel = await screen.findByTestId('acts-as-user-select') as HTMLSelectElement
    expect([...sel.options].map((o) => o.text)).toContain('Russ Addison')
    fireEvent.change(sel, { target: { value: '21' } })
    expect(getActsAsUserId()).toBe(21)
    expect(getActsAsDepartmentId()).toBeNull()
    expect(reload).toHaveBeenCalled()
    const cfg = attachActsAs({ headers: {} as Record<string, unknown> })
    expect(cfg.headers['X-Acts-As-User']).toBe('21')
    expect(cfg.headers['X-Acts-As-Department']).toBeUndefined()
  })

  it('the viewing-as banner names the person and goes back to me', () => {
    setActsAsUserId(21)
    rtlRender(<ViewingAsBanner name="Russ Addison" />)
    expect(screen.getByTestId('viewing-as-banner').textContent).toContain('Viewing as Russ Addison')
    fireEvent.click(screen.getByTestId('viewing-as-back'))
    expect(getActsAsUserId()).toBeNull()
    expect(reload).toHaveBeenCalled()
  })
})
