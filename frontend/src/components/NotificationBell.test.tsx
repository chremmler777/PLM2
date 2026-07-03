import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import NotificationBell from './NotificationBell'

// NotificationBell fetches unread count + the notification list via the shared
// axios client (default export). Grouping is derived client-side from n.link.
const clientMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const notifications = [
  { id: 1, title: 'D1 gate blocked', body: null, link: '/changes/1?tab=d1', is_read: false, created_at: '2026-07-02T10:00:00' },
  { id: 2, title: 'D1 gate resolved', body: null, link: '/changes/1?tab=d1', is_read: false, created_at: '2026-07-01T10:00:00' },
  { id: 3, title: 'New change captured', body: null, link: '/changes/2', is_read: false, created_at: '2026-06-30T10:00:00' },
]

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><NotificationBell collapsed={false} /></MemoryRouter>
    </QueryClientProvider>
  )
}

describe('NotificationBell inbox grouping', () => {
  afterEach(cleanup)

  it('groups notifications by link path under 2 headers', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.includes('unread-count')) return Promise.resolve({ data: { count: 3 } })
      if (url.includes('/v1/notifications')) return Promise.resolve({ data: notifications })
      return Promise.resolve({ data: [] })
    })

    wrap()
    fireEvent.click(screen.getByTitle('Notifications'))

    await waitFor(() => expect(screen.getByText('D1 gate blocked')).toBeDefined())

    expect(screen.getByText('/changes/1')).toBeDefined()
    expect(screen.getByText('/changes/2')).toBeDefined()
    expect(screen.getAllByText('D1 gate blocked').length + screen.getAllByText('D1 gate resolved').length).toBe(2)
    expect(screen.getByText('New change captured')).toBeDefined()
  })
})
