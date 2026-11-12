import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ProjectLopPage from './ProjectLopPage'
import { lopProject } from '../components/lop/lop.fixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../components/lop/LopPanel', () => ({
  default: (p: { projectId: number }) => <div data-testid="lop-panel-stub">lop panel {p.projectId}</div>,
}))

function mount(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/projects/:projectId/lop" element={<ProjectLopPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>)
}

describe('ProjectLopPage', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
  })
  afterEach(cleanup)

  it('renders the panel for the project in the URL and says so when the project has no LOP', async () => {
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/2') return Promise.resolve({ data: lopProject() })
      return Promise.resolve({ data: [] })
    })
    mount('/projects/2/lop')
    expect((await screen.findByTestId('lop-panel-stub')).textContent).toBe('lop panel 2')
    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('2277')
    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('Backpanel')
    expect(screen.getByRole('link', { name: /back to the project/i }).getAttribute('href')).toBe('/projects/2')
    cleanup()

    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/lop/projects/7') return Promise.reject({ response: { status: 404, data: { detail: 'LOP not found' } } })
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 7, code: '1864', name: 'Door trim' }] })
      return Promise.resolve({ data: [] })
    })
    mount('/projects/7/lop')
    expect(await screen.findByText('This project has no LOP.')).toBeTruthy()
    expect(screen.queryByTestId('lop-panel-stub')).toBeNull()
    expect(screen.getByRole('link', { name: /back to the project/i }).getAttribute('href')).toBe('/projects/7')
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('1864'))
  })

  it('shows the server\'s detail when the LOP cannot be loaded', async () => {
    clientMocks.get.mockImplementation(() => Promise.reject({ response: { status: 500, data: { detail: 'Database is busy' } } }))
    mount('/projects/2/lop')
    expect((await screen.findByRole('alert')).textContent).toContain('Database is busy')
    expect(screen.queryByTestId('lop-panel-stub')).toBeNull()
  })
})
