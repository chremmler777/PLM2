import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScopingFlags from './ScopingFlags'
import { t } from '../../../i18n/cmLabels'

vi.mock('../../../api/changes', () => ({ changesApi: { raiseConcern: vi.fn(), joinConcern: vi.fn() } }))

afterEach(() => cleanup())

const DEPTS = [{ id: 3, name: 'Process Engineer', is_active: true }]

describe('Scoping takes blocking questions only (2026-10-27)', () => {
  it('the quick add raises a question, offers no check item and shows no empty check list', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ScopingFlags changeId={7} concerns={[]} impactedItems={[]} departments={DEPTS}
          myDepartmentIds={[3]} changeDepartmentIds={[3]} editable onChanged={() => {}} />
      </QueryClientProvider>)
    expect(screen.getByTestId('quick-add-submit').textContent).toBe(t('flag.addQuestion'))
    expect(screen.queryByTestId('quick-add-question')).toBeNull()
    expect(screen.queryByTestId('check-items')).toBeNull()
  })
})
