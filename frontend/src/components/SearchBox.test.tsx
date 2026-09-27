import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import SearchBox from './SearchBox'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

afterEach(cleanup)

function Where() {
  const loc = useLocation()
  return <p data-testid="where">{loc.pathname + loc.search}</p>
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SearchBox />
        <Routes><Route path="*" element={<Where />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SearchBox combobox', () => {
  it('exposes the combobox pattern and navigates with the keyboard', async () => {
    clientMocks.get.mockResolvedValue({ data: {
      projects: [{ id: 7, name: 'Atlas', code: 'VW426' }],
      parts: [{ id: 3, part_number: '3CR.807', name: 'Grille', part_type: 'part', item_category: 'article', project_id: 7, project_name: 'Atlas' }],
    } })
    wrap()
    const input = screen.getByRole('combobox', { name: 'Search parts and projects' })
    expect(input.getAttribute('aria-expanded')).toBe('false')
    expect(input.hasAttribute('aria-controls')).toBe(false)

    fireEvent.change(input, { target: { value: 'atl' } })
    const list = await screen.findByRole('listbox', {}, { timeout: 2000 })
    expect(input.getAttribute('aria-expanded')).toBe('true')
    expect(input.getAttribute('aria-controls')).toBe(list.id)
    const opts = screen.getAllByRole('option')
    expect(opts).toHaveLength(2)
    expect(input.hasAttribute('aria-activedescendant')).toBe(false)

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input.getAttribute('aria-activedescendant')).toBe(opts[1].id)
    expect(opts[1].getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input.getAttribute('aria-activedescendant')).toBe(opts[0].id)

    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByTestId('where').textContent).toBe('/projects/7')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(input.getAttribute('aria-expanded')).toBe('false')
  })

  it('has no listbox and no aria-controls when nothing matches', async () => {
    clientMocks.get.mockResolvedValue({ data: { projects: [], parts: [] } })
    wrap()
    const input = screen.getByRole('combobox')
    fireEvent.change(input, { target: { value: 'zzz' } })
    expect((await screen.findAllByText(/No parts or projects match/, {}, { timeout: 2000 })).length).toBeGreaterThan(0)
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(input.getAttribute('aria-expanded')).toBe('false')
    expect(input.hasAttribute('aria-controls')).toBe(false)
  })
})
