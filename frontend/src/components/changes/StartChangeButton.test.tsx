import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import StartChangeButton from './StartChangeButton'
import { t } from '../../i18n/cmLabels'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = (onClick = vi.fn()) => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StartChangeButton label="New Change Request" onClick={onClick} />
    </QueryClientProvider>)
  return onClick
}

describe('StartChangeButton', () => {
  beforeEach(() => clientMocks.get.mockReset())
  afterEach(cleanup)

  it('lets a permitted user through', async () => {
    clientMocks.get.mockResolvedValue({ data: { can_start_change: true } })
    const onClick = wrap()
    const btn = await screen.findByTestId('start-change') as HTMLButtonElement
    await waitFor(() => expect(btn.disabled).toBe(false))
    fireEvent.click(btn)
    expect(onClick).toHaveBeenCalled()
  })

  it('greys the button and names the rule for anyone else', async () => {
    clientMocks.get.mockResolvedValue({ data: { can_start_change: false } })
    const onClick = wrap()
    const btn = await screen.findByTestId('start-change') as HTMLButtonElement
    await waitFor(() => expect(btn.disabled).toBe(true))
    expect(btn.getAttribute('title')).toBe(t('start.salesOnly'))
    fireEvent.click(btn)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('stays usable when the answer says nothing about the permission', async () => {
    // Fail-open: an older payload (or an endpoint that is not there yet) must
    // not lock Sales out of their own job; the POST's 403 still guards it.
    clientMocks.get.mockResolvedValue({ data: {} })
    const onClick = wrap()
    const btn = await screen.findByTestId('start-change') as HTMLButtonElement
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalled())
    expect(btn.disabled).toBe(false)
    fireEvent.click(btn)
    expect(onClick).toHaveBeenCalled()
  })
})
