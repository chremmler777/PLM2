import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CustomerNamingSelect } from './ProjectDetailPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('CustomerNamingSelect', () => {
  beforeEach(() => { clientMocks.patch.mockReset() })
  afterEach(cleanup)

  it('shows the current convention and saves a change', async () => {
    clientMocks.patch.mockResolvedValue({ data: { id: 2, customer_naming: 'vw' } })
    wrap(<CustomerNamingSelect projectId={2} value={null} />)
    const sel = screen.getByLabelText('Customer file naming') as HTMLSelectElement
    expect(sel.value).toBe('')
    fireEvent.change(sel, { target: { value: 'vw' } })
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/plants/projects/2', { customer_naming: 'vw' }))
  })

  it('clears with null', async () => {
    clientMocks.patch.mockResolvedValue({ data: { id: 2, customer_naming: null } })
    wrap(<CustomerNamingSelect projectId={2} value="scout" />)
    const sel = screen.getByLabelText('Customer file naming') as HTMLSelectElement
    expect(sel.value).toBe('scout')
    fireEvent.change(sel, { target: { value: '' } })
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/plants/projects/2', { customer_naming: null }))
  })
})
