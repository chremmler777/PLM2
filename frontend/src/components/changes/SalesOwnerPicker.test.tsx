import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SalesOwnerPicker from './SalesOwnerPicker'

const setSalesOwner = vi.fn().mockResolvedValue({})
const salesOwnerCandidates = vi.fn()
vi.mock('../../api/changes', () => ({
  changesApi: {
    setSalesOwner: (...a: unknown[]) => setSalesOwner(...a),
    salesOwnerCandidates: (...a: unknown[]) => salesOwnerCandidates(...a),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
)

describe('SalesOwnerPicker (ECR-solid C10)', () => {
  afterEach(() => { cleanup(); salesOwnerCandidates.mockClear() })

  it('says all of Sales when nobody owns it, and Sales picks the owner', async () => {
    salesOwnerCandidates.mockResolvedValue([
      { id: 3, name: 'Cody Sales', is_default: true }, { id: 4, name: 'Jubei Sales' },
    ])
    render(wrap(<SalesOwnerPicker change={{ id: 7, sales_owner_id: null, sales_owner_name: null }} canEdit />))
    expect(screen.getByTestId('sales-owner-name').textContent).toBe('No Sales contact: all of Sales')
    fireEvent.click(screen.getByTestId('sales-owner-edit'))
    const sel = () => screen.getByTestId('sales-owner-select') as HTMLSelectElement
    await waitFor(() => expect(sel().options.length).toBe(3))
    fireEvent.change(sel(), { target: { value: '4' } })
    await waitFor(() => expect(setSalesOwner).toHaveBeenCalledWith(7, 4))
  })

  it('opens on the placeholder, so the marked project contact can be picked and saved', async () => {
    salesOwnerCandidates.mockResolvedValue([
      { id: 3, name: 'Cody Sales', is_default: true }, { id: 4, name: 'Jubei Sales' },
    ])
    render(wrap(<SalesOwnerPicker change={{ id: 7, sales_owner_id: null, sales_owner_name: null }} canEdit />))
    fireEvent.click(screen.getByTestId('sales-owner-edit'))
    const sel = () => screen.getByTestId('sales-owner-select') as HTMLSelectElement
    await waitFor(() => expect(sel().options.length).toBe(3))
    expect(sel().value).toBe('')
    expect(sel().options[1].textContent).toBe('Cody Sales (project contact)')
    fireEvent.change(sel(), { target: { value: '3' } })
    await waitFor(() => expect(setSalesOwner).toHaveBeenCalledWith(7, 3))
  })

  it('reads only, without a change button, for everyone else', () => {
    render(wrap(<SalesOwnerPicker change={{ id: 7, sales_owner_id: 3, sales_owner_name: 'Cody Sales' }}
      canEdit={false} />))
    expect(screen.getByTestId('sales-owner-name').textContent).toBe('Cody Sales')
    expect(screen.queryByTestId('sales-owner-edit')).toBeNull()
    expect(salesOwnerCandidates).not.toHaveBeenCalled()
  })
})
