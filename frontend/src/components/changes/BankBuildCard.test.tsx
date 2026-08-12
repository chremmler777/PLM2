import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BankBuildCard from './BankBuildCard'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

vi.mock('../../api/changes', () => ({
  changesApi: { setBankBuild: vi.fn(), publishBankBuildPlan: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const change = (over: Record<string, unknown> = {}) => ({
  id: 7, status: 'approved',
  bank_build_mode: null, bank_build_note: null, scrap_quote_price: null,
  bank_build_set_by_name: null, bank_build_set_at: null,
  plan_published_by_name: null, plan_published_at: null, ...over,
}) as never

const wrap = (props: {
  change?: never; canSetMode?: boolean; canPublish?: boolean
} = {}) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <BankBuildCard change={props.change ?? change()}
      canSetMode={props.canSetMode ?? true} canPublish={props.canPublish ?? false} />
  </QueryClientProvider>)

describe('BankBuildCard', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(changesApi.setBankBuild).mockResolvedValue({} as never)
    vi.mocked(changesApi.publishBankBuildPlan).mockResolvedValue({} as never)
  })

  it('saves a running change with its plan note and no scrap price', async () => {
    wrap()
    fireEvent.click(screen.getByTestId('bank-build-mode-running_change'))
    fireEvent.change(screen.getByTestId('bank-build-note'),
      { target: { value: 'cut over at CW38 in Ostrava' } })
    fireEvent.click(screen.getByTestId('bank-build-save'))
    await waitFor(() => expect(changesApi.setBankBuild).toHaveBeenCalledWith(7, {
      mode: 'running_change', note: 'cut over at CW38 in Ostrava',
    }))
  })

  it('asks for the scrap price only for planned scrap, and will not save without it', async () => {
    wrap()
    // Running change: no price anywhere.
    fireEvent.click(screen.getByTestId('bank-build-mode-running_change'))
    expect(screen.queryByTestId('bank-build-scrap-price')).toBeNull()

    fireEvent.click(screen.getByTestId('bank-build-mode-planned_scrap'))
    expect(screen.getByTestId('bank-build-scrap-price')).toBeTruthy()
    // The customer bears the scrap — the card says so where the number is typed.
    expect(screen.getByTestId('bank-build-scrap-hint').textContent)
      .toBe(t('bankbuild.scrapPriceHint'))
    // Priced at nothing is not a decision: the save stays shut.
    const save = screen.getByTestId('bank-build-save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    expect(screen.getByTestId('bank-build-need-price').textContent)
      .toBe(t('bankbuild.needPrice'))

    fireEvent.change(screen.getByTestId('bank-build-scrap-price'), { target: { value: '4200' } })
    expect((screen.getByTestId('bank-build-save') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByTestId('bank-build-save'))
    await waitFor(() => expect(changesApi.setBankBuild).toHaveBeenCalledWith(7, {
      mode: 'planned_scrap', scrap_quote_price: 4200,
    }))
  })

  it('holds the save shut until a mode is picked', () => {
    wrap()
    expect((screen.getByTestId('bank-build-save') as HTMLButtonElement).disabled).toBe(true)
  })

  it('gates publishing on the mode being set, then publishes', async () => {
    const { unmount } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <BankBuildCard change={change()} canSetMode={false} canPublish />
      </QueryClientProvider>)
    expect((screen.getByTestId('bank-build-publish') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('bank-build-publish-blocked').textContent)
      .toBe(t('bankbuild.publishNeedsMode'))
    unmount()

    wrap({ change: change({ bank_build_mode: 'running_change' }), canSetMode: false, canPublish: true })
    expect(screen.getByTestId('bank-build-publish-state').textContent)
      .toBe(t('bankbuild.unpublished'))
    fireEvent.click(screen.getByTestId('bank-build-publish'))
    await waitFor(() => expect(changesApi.publishBankBuildPlan).toHaveBeenCalledWith(7))
  })

  it('names who published the plan and drops the button once it is out', () => {
    wrap({
      change: change({
        bank_build_mode: 'running_change',
        plan_published_by_name: 'sales.anna', plan_published_at: '2026-08-10T09:00:00',
      }),
      canSetMode: false, canPublish: true,
    })
    expect(screen.getByTestId('bank-build-publish-state').textContent)
      .toContain('sales.anna')
    expect(screen.queryByTestId('bank-build-publish')).toBeNull()
  })

  it('shows the decision read-only to someone who may not set it', () => {
    wrap({
      change: change({
        bank_build_mode: 'planned_scrap', scrap_quote_price: 4200,
        bank_build_note: 'scrap 380 pcs at Ostrava',
        bank_build_set_by_name: 'sched.max', bank_build_set_at: '2026-08-09T09:00:00',
      }),
      canSetMode: false,
    })
    expect(screen.queryByTestId('bank-build-mode-planned_scrap')).toBeNull()
    expect(screen.queryByTestId('bank-build-save')).toBeNull()
    const view = screen.getByTestId('bank-build-readonly')
    expect(view.textContent).toContain(t('bankbuild.mode.planned_scrap'))
    expect(view.textContent).toContain('4200.00')
    expect(view.textContent).toContain('scrap 380 pcs at Ostrava')
    expect(view.textContent).toContain('sched.max')
    expect(view.textContent).toContain(t('bankbuild.readOnly'))
  })

  it('stops being editable once the change has left approved', () => {
    // The backend only takes the decision at `approved`; afterwards the card is
    // the record of what was decided, for Scheduling too.
    wrap({ change: change({ status: 'in_implementation', bank_build_mode: 'running_change' }) })
    expect(screen.queryByTestId('bank-build-save')).toBeNull()
    expect(screen.getByTestId('bank-build-readonly').textContent)
      .toContain(t('bankbuild.mode.running_change'))
  })
})
