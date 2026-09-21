import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import PaintsPage from './PaintsPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const paint = (over: Record<string, unknown> = {}) => ({
  id: 1,
  name: 'RAL 9005 Basecoat',
  paint_type: 'basecoat',
  colour_code: 'RAL 9005',
  colour_name: 'Jet Black',
  colour_hex: '#0a0a0a',
  supplier_id: null,
  supplier_text: 'AkzoNobel',
  spec_reference: 'SPEC-1',
  notes: null,
  is_active: true,
  ...over,
})

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PaintsPage />
    </QueryClientProvider>
  )
}

describe('PaintsPage', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.post.mockReset()
    clientMocks.put.mockReset()
    vi.mocked(toast.error).mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/paints') return Promise.resolve({ data: [paint()] })
      if (url === '/v1/paints/1/used-in') {
        return Promise.resolve({
          data: [
            { part_id: 5, part_number: '1994-100', name: 'Bracket', project_id: 2, project_code: 'VW426', layer_order: 2 },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('renders the paint list from the mock', async () => {
    renderPage()
    expect(await screen.findByText('RAL 9005 Basecoat')).toBeTruthy()
    expect(screen.getByText('RAL 9005')).toBeTruthy()
  })

  it('filters by search term via the q param', async () => {
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')

    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'clear' } })

    await waitFor(() =>
      expect(clientMocks.get).toHaveBeenCalledWith(
        '/v1/paints',
        expect.objectContaining({ params: expect.objectContaining({ q: 'clear' }) })
      )
    )
  })

  it('toggles active_only when show inactive is checked', async () => {
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')

    // Default: active_only true (not showing inactive)
    expect(clientMocks.get).toHaveBeenCalledWith(
      '/v1/paints',
      expect.objectContaining({ params: expect.objectContaining({ active_only: true }) })
    )

    fireEvent.click(screen.getByLabelText(/show inactive/i))

    await waitFor(() =>
      expect(clientMocks.get).toHaveBeenCalledWith(
        '/v1/paints',
        expect.objectContaining({ params: expect.objectContaining({ active_only: false }) })
      )
    )
  })

  it('posts the payload from the new paint form', async () => {
    clientMocks.post.mockResolvedValue({ data: paint({ id: 2, name: 'New Paint' }) })
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')

    fireEvent.click(screen.getByRole('button', { name: /new paint/i }))
    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'New Paint' } })
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }))

    await waitFor(() => expect(clientMocks.post).toHaveBeenCalled())
    expect(clientMocks.post.mock.calls[0][0]).toBe('/v1/paints')
    expect(clientMocks.post.mock.calls[0][1]).toMatchObject({ name: 'New Paint' })
  })

  it('puts the payload from the edit paint form', async () => {
    clientMocks.put.mockResolvedValue({ data: paint({ name: 'Updated Name' }) })
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')

    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'Updated Name' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(clientMocks.put).toHaveBeenCalled())
    expect(clientMocks.put.mock.calls[0][0]).toBe('/v1/paints/1')
    expect(clientMocks.put.mock.calls[0][1]).toMatchObject({ name: 'Updated Name' })
  })

  // FastAPI answers a 422 with `detail` as an ARRAY; handing that to
  // toast.error() used to make React render an object and take the app down.
  const validationError = () => ({
    response: {
      status: 422,
      data: {
        detail: [
          { type: 'string_pattern_mismatch', loc: ['body', 'colour_hex'], msg: 'String should match pattern' },
        ],
      },
    },
  })

  it('shows a toast string when creating a paint fails validation with a 422', async () => {
    clientMocks.post.mockRejectedValue(validationError())
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')

    fireEvent.click(screen.getByRole('button', { name: /new paint/i }))
    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'Bad hex' } })
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    const calls = vi.mocked(toast.error).mock.calls
    const arg = calls[calls.length - 1][0]
    expect(typeof arg).toBe('string')
    expect(arg).toContain('String should match pattern')
    // the modal survives: the page did not crash
    expect(screen.getByText('New Paint')).toBeTruthy()
  })

  it('shows a toast string when updating a paint fails validation with a 422', async () => {
    clientMocks.put.mockRejectedValue(validationError())
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')

    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    const calls = vi.mocked(toast.error).mock.calls
    const arg = calls[calls.length - 1][0]
    expect(typeof arg).toBe('string')
    expect(arg).toContain('String should match pattern')
    expect(screen.getByText(/Edit Paint/)).toBeTruthy()
  })

  it('gives the colour hex input a #RRGGBB placeholder and pattern', async () => {
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')
    fireEvent.click(screen.getByRole('button', { name: /new paint/i }))

    const hex = screen.getByLabelText(/colour hex/i) as HTMLInputElement
    expect(hex.placeholder).toBe('#RRGGBB')
    expect(hex.getAttribute('pattern')).toBe('^#[0-9a-fA-F]{6}$')
  })

  it('expanding a row loads used-in and shows part numbers', async () => {
    renderPage()
    await screen.findByText('RAL 9005 Basecoat')

    fireEvent.click(screen.getByRole('button', { name: /RAL 9005 Basecoat/i }))

    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith('/v1/paints/1/used-in'))
    expect(await screen.findByText('1994-100')).toBeTruthy()
  })
})
