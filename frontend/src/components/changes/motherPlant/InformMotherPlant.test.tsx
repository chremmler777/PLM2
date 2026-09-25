import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import InformMotherPlant from './InformMotherPlant'
import type { ChangeRequest } from '../../../types/change'

const api = vi.hoisted(() => ({ inform: vi.fn() }))
vi.mock('../../../api/motherPlant', async (orig) => ({
  ...(await orig<typeof import('../../../api/motherPlant')>()), motherPlantApi: api,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const change = (over: Record<string, unknown> = {}) => ({
  id: 9, status: 'approved', origin: 'mother_plant', mother_plant_name: 'KTX Weissenburg (WUG)',
  plan_published_at: null, plan_published_by_name: null, ...over,
}) as unknown as ChangeRequest

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('InformMotherPlant', () => {
  afterEach(cleanup)

  it('stamps "Inform KTX Weissenburg" after the baseline', async () => {
    api.inform.mockResolvedValue({})
    wrap(<InformMotherPlant change={change()} canInform timingValidated />)
    fireEvent.click(screen.getByTestId('timing-inform-mother-button'))
    await waitFor(() => expect(api.inform).toHaveBeenCalledWith(9))
    expect(screen.queryByText(/Publish plan to customer/)).toBeNull()
  })

  it('shows the stamp and offers a re-inform', () => {
    wrap(<InformMotherPlant change={change({ plan_published_at: '2026-09-12T10:00:00', plan_published_by_name: 'Paula PM' })}
      canInform timingValidated />)
    expect(screen.getByTestId('timing-mother-informed').textContent)
      .toContain('KTX Weissenburg informed of the timing 12.09.2026 by Paula PM')
    expect(screen.getByTestId('timing-inform-mother-button').textContent).toBe('Inform KTX Weissenburg again')
  })

  it('without the right, names who does it', () => {
    wrap(<InformMotherPlant change={change()} canInform={false} timingValidated />)
    expect(screen.queryByTestId('timing-inform-mother-button')).toBeNull()
    expect(screen.getByText('Project Management informs KTX Weissenburg.')).toBeDefined()
  })
})
