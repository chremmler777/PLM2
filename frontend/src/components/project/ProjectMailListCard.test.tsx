import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProjectMailListCard } from './ProjectMailListCard'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe('ProjectMailListCard', () => {
  beforeEach(() => {
    clientMocks.get.mockResolvedValue({ data: [
      { id: 1, email: 'dale.perry@us.ktx.group', display_name: 'Dale Perry', active: true },
    ] })
    clientMocks.post.mockResolvedValue({ data: {} })
    clientMocks.delete.mockResolvedValue({})
  })
  afterEach(cleanup)

  it('lists the recipients by name', async () => {
    wrap(<ProjectMailListCard projectId={2} />)
    await screen.findByText('Dale Perry')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/projects/2/mail-recipients')
  })

  it('adds an address', async () => {
    wrap(<ProjectMailListCard projectId={2} />)
    const input = await screen.findByTestId('mail-add-input')
    fireEvent.change(input, { target: { value: 'karl.limburg@us.ktx.group' } })
    fireEvent.click(screen.getByTestId('mail-add'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith(
      '/v1/projects/2/mail-recipients', { email: 'karl.limburg@us.ktx.group' }))
  })

  it('removes an address', async () => {
    wrap(<ProjectMailListCard projectId={2} />)
    fireEvent.click(await screen.findByTestId('mail-remove-1'))
    await waitFor(() => expect(clientMocks.delete).toHaveBeenCalledWith('/v1/projects/2/mail-recipients/1'))
  })

  it('stays hidden when the server refuses the list', async () => {
    clientMocks.get.mockRejectedValue({ response: { status: 403 } })
    wrap(<ProjectMailListCard projectId={2} />)
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByTestId('project-mail-list-card')).toBeNull()
  })
})
