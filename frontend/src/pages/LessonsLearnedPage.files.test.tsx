import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LessonDetailModal } from './LessonsLearnedPage'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const lesson = (files: Record<string, unknown>[]) => ({
  id: 1, title: 'Clip rattles', description: 'd',
  category: 'design', lesson_type: 'problem', severity: 'medium',
  root_cause: null, recommendation: null, tags: null, status: 'open',
  owner_id: null, owner_name: null, target_date: null, target_overdue: false,
  reject_category: null, reject_reason: null,
  created_by_name: 'Eva Eng', created_at: '2026-07-01T00:00:00',
  days_in_state: 1, stale: false, open_actions: 0, total_actions: 0,
  allowed_transitions: [], editable_fields: [],
  effectiveness_note: null, actions: [], comments: [], files,
})

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

describe('Lesson evidence provenance', () => {
  beforeEach(() => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url.startsWith('/v1/lessons/1')) return Promise.resolve({ data: lesson([
        { id: 4, filename: 'photo.jpg', size_bytes: 2048, created_at: '2026-07-02T00:00:00',
          uploaded_by: 5, uploaded_by_name: 'Rita RD' },
        { id: 5, filename: 'old.pdf', size_bytes: 1024, created_at: '2026-07-03T00:00:00' },
      ]) })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('names who attached each evidence file, falling back to the date alone', async () => {
    wrap(<LessonDetailModal lessonId={1} onClose={() => {}} />)
    const lines = await screen.findAllByTestId('uploaded-by')
    expect(lines[0].textContent)
      .toBe(`Rita RD · ${new Date('2026-07-02T00:00:00').toLocaleDateString()}`)
    expect(lines[1].textContent).toBe(new Date('2026-07-03T00:00:00').toLocaleDateString())
  })
})
