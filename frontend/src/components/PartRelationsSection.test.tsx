import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PartRelationsSection from './PartRelationsSection'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe('PartRelationsSection relation type select', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
  })
  afterEach(cleanup)

  it('offers "mirror of" for an article', async () => {
    wrap(<PartRelationsSection partId={1} itemCategory="article" projectParts={[]} />)
    fireEvent.click(screen.getByText('+ Link Item'))
    const option = await screen.findByRole('option', { name: 'mirror of' }) as HTMLOptionElement
    expect(option.value).toBe('mirror_of')
  })

  it('does not offer "mirror of" for a tool', async () => {
    wrap(<PartRelationsSection partId={1} itemCategory="tool" projectParts={[]} />)
    fireEvent.click(screen.getByText('+ Link Item'))
    expect(screen.queryByRole('option', { name: 'mirror of' })).toBeNull()
  })
})
