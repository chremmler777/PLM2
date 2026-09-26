import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DiffPanel from './DiffPanel'
import type { CostSheetDiff } from '../../types/costSheet'

vi.mock('../../api/costSheetMachines', () => ({
  costSheetMachinesApi: {
    list: vi.fn().mockResolvedValue({ machines: [
      { id: 1, internal_name: 'P-350' }, { id: 2, internal_name: 'M-300', local_currency: 'MXN' }] }),
  },
}))

const empty = { added: [], removed: [], changed: [] }

describe('DiffPanel machine rates', () => {
  afterEach(cleanup)

  it('shows currency, note and typed local changes, the old rate in its old currency', async () => {
    const diff: CostSheetDiff = {
      from_version: 1, from_version_id: 1, to_version: 2, to_version_id: 2,
      rates: empty, machines: empty, sampling: empty, overheads: empty,
      machine_items: {
        added: [], removed: [],
        changed: [
          { machine_id: 1, currency: 'USD', changes: {
            hourly_rate: { old: 90, new: 99 }, currency: { old: 'EUR', new: 'USD' },
            note: { old: null, new: 'new tooling' } }, pct: 10 },
          { machine_id: 2, currency: 'USD', changes: {
            hourly_rate: { old: 98.27, new: 100 }, entered_rate: { old: 1700, new: 1730 },
            } },
        ],
      },
    } as unknown as CostSheetDiff
    render(
      <QueryClientProvider client={new QueryClient()}>
        <DiffPanel diff={diff} ctx={{ departments: [], plants: [], machineClasses: [], currencies: [] }} />
      </QueryClientProvider>)
    const p350 = screen.getByTestId('diff-machine-item-1')
    await waitFor(() => expect(p350.textContent).toMatch(/P-350/))
    expect(p350.textContent).toMatch(/Rate \/ h: 90\.00 EUR\s*99\.00 USD/)
    expect(p350.textContent).not.toMatch(/\+10/)            // no percent across currencies
    expect(p350.textContent).toMatch(/Currency: EUR\s*USD/)
    expect(p350.textContent).toMatch(/Note: -\s*new tooling/)
    const m300 = screen.getByTestId('diff-machine-item-2')
    expect(m300.textContent).toMatch(/Typed local: 1,700\.00 MXN\s*1,730\.00 MXN/)
  })
})
