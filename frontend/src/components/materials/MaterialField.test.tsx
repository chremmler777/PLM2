import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MaterialField from './MaterialField'
import { materialOf } from '../../lib/material'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const hits = [{ id: 11, ktx_number: '40-1234', trade_name: 'Ultramid B3WG6', grade: 'black 00564', manufacturer: 'BASF',
  family: 'PA6', classification: 'series', label: '40-1234 Ultramid B3WG6 black 00564' }]

function mount(material = materialOf({})) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><MaterialField partId={5} material={material} /></QueryClientProvider>)
}

describe('MaterialField', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.put.mockReset(); clientMocks.post.mockReset()
    clientMocks.get.mockResolvedValue({ data: hits })
    clientMocks.put.mockResolvedValue({ data: {} })
    clientMocks.post.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows a linked material as a MaterialDB link', () => {
    mount({ ...materialOf({}), material_source: 'materialdb', materialdb_id: 11, material_label: '40-1234 Ultramid B3WG6 black 00564' })
    const link = screen.getByTestId('material-value') as HTMLAnchorElement
    expect(link.textContent).toBe('40-1234 Ultramid B3WG6 black 00564')
    expect(link.getAttribute('href')).toBe('/materialdb/materials/11')
    expect(screen.getByTestId('material-refresh')).toBeTruthy()
  })

  it('marks a new material clearly', () => {
    mount({ ...materialOf({}), material_source: 'new', material_new_text: 'PA6-GF15 acc. VW 50125' })
    expect(screen.getByTestId('material-value').textContent).toContain('PA6-GF15 acc. VW 50125')
    expect(screen.getByTestId('material-value-new').textContent).toBe('NEW, not in MaterialDB')
  })

  it('searches MaterialDB and links the pick', async () => {
    mount()
    fireEvent.click(screen.getByTestId('material-change'))
    fireEvent.change(screen.getByTestId('material-search-input'), { target: { value: 'ultramid' } })
    fireEvent.click(await screen.findByTestId('material-hit-11', {}, { timeout: 2000 }))
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/materials/search', { params: { q: 'ultramid' } })
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5/material', { source: 'materialdb', materialdb_id: 11 }))
  })

  it('saves a new material that is not in MaterialDB', async () => {
    mount()
    fireEvent.click(screen.getByTestId('material-change'))
    fireEvent.click(screen.getByTestId('material-mode-new'))
    fireEvent.change(screen.getByTestId('material-new-input'), { target: { value: ' PP-TD20 ' } })
    fireEvent.click(screen.getByTestId('material-new-save'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5/material', { source: 'new', new_text: 'PP-TD20' }))
  })

  it('says clearly when MaterialDB is not reachable', async () => {
    clientMocks.get.mockRejectedValue({ response: { status: 503, data: { detail: 'MaterialDB is unreachable (ConnectError); try again later' } } })
    mount()
    fireEvent.click(screen.getByTestId('material-change'))
    fireEvent.change(screen.getByTestId('material-search-input'), { target: { value: 'ultramid' } })
    expect((await screen.findByTestId('material-search-error', {}, { timeout: 2000 })).textContent).toContain('MaterialDB is unreachable')
  })
})
