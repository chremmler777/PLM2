import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScopeDefinitionBlock from './ScopeDefinitionBlock'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: { setScopeDefinition: vi.fn().mockResolvedValue({}) },
}))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)
const change = (over: Record<string, unknown> = {}) =>
  ({ id: 7, status: 'scoping', scope_definition: null, ...over }) as never

describe('ScopeDefinitionBlock', () => {
  afterEach(cleanup)

  it('lets PM define the scope during scoping and saves it trimmed', async () => {
    wrap(<ScopeDefinitionBlock change={change()} canEdit />)
    expect(screen.getByText(t('scope.title'))).toBeTruthy()
    fireEvent.click(screen.getByTestId('scope-edit'))
    fireEvent.change(screen.getByTestId('scope-input'), { target: { value: ' Insert only ' } })
    fireEvent.click(screen.getByTestId('scope-save'))
    await waitFor(() => expect(changesApi.setScopeDefinition).toHaveBeenCalledWith(7, 'Insert only'))
  })

  it('shows the text read only to everyone else, with who defines it', () => {
    wrap(<ScopeDefinitionBlock change={change({ scope_definition: 'Insert only' })} />)
    expect(screen.getByTestId('scope-text').textContent).toBe('Insert only')
    expect(screen.queryByTestId('scope-edit')).toBeNull()
    expect(screen.getByTestId('scope-rights').textContent).toBe(t('scope.rights'))
  })

  it('is read only after scoping, even for PM', () => {
    wrap(<ScopeDefinitionBlock change={change({ status: 'in_assessment', scope_definition: 'Insert only' })} canEdit />)
    expect(screen.queryByTestId('scope-edit')).toBeNull()
    expect(screen.getByTestId('scope-rights').textContent).toBe(t('scope.readOnly'))
  })

  it('leaves no empty box where it is only read', () => {
    wrap(<ScopeDefinitionBlock change={change({ status: 'costing' })} hideWhenEmpty />)
    expect(screen.queryByTestId('scope-definition')).toBeNull()
  })
})
