import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MachinesPanel, { machineStatus } from './MachinesPanel'
import { costSheetMachinesApi } from '../../api/costSheetMachines'
import type { CostSheetMachine, MachinesListing } from '../../types/costSheetMachines'

vi.mock('../../api/costSheetMachines', () => ({
  costSheetMachinesApi: {
    list: vi.fn(), sync: vi.fn(), setRate: vi.fn(), setPlantMap: vi.fn(), deletePlantMap: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const plants = [
  { id: 2, name: 'USA Toccoa', code: 'usa', is_active: true, currency: 'USD', currency_confirmed: true },
  { id: 5, name: 'Silao Mexico', code: 'SIL', is_active: true, currency: 'USD', currency_confirmed: true },
]

function machine(over: Partial<CostSheetMachine>): CostSheetMachine {
  return {
    id: 1, machinedb_id: 10, internal_name: 'P-80', machinedb_plant: 'usa', plant_id: 2,
    clamping_force_t: 80, tonnage_class: null, two_k_type: null, manufacturer: 'Engel', model: null,
    in_service_from: null, planned_scrap_from: null, active: true, retired: false, synced_at: null,
    machine_class_id: 1, machine_class: '<=200 t', rate_id: null, hourly_rate: null, currency: null,
    note: null, class_rate: 85, class_rate_currency: 'USD', plant_currency: 'USD',
    entered_rate: null, entered_currency: null, local_currency: null, local_rate: null,
    entered_in: null, ...over,
  }
}

function listing(over: Partial<MachinesListing> = {}): MachinesListing {
  return {
    version_id: 9,
    machines: [
      machine({}),
      machine({ id: 2, internal_name: 'P-350', clamping_force_t: 350, machine_class: '200-450 t',
        hourly_rate: 120, currency: 'USD' }),
      machine({ id: 3, internal_name: 'M-300', machinedb_plant: 'mexico', plant_id: 5,
        two_k_type: '2k_turntable', active: false, planned_scrap_from: '2026-06-30' }),
      machine({ id: 4, internal_name: 'S-500', machinedb_plant: 'solingen', plant_id: null,
        plant_currency: null }),
    ],
    machinedb: { configured: true, missing: [], host: 'machinedb-backend' },
    last_sync: { at: '2026-09-26T08:00:00', total: 4, new: 4, changed: 0, retired: 0, unmapped: 1 },
    can_sync: true, can_edit_rates: true, currencies: ['EUR', 'USD', 'MXN'],
    plant_map: {
      usa: { plant_id: 2, source: 'default' }, mexico: { plant_id: 5, source: 'default' },
      solingen: { plant_id: null, source: 'no default for this MachineDB plant' },
    },
    ...over,
  }
}

const wrap = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

describe('MachinesPanel', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('groups machines by plant, unmapped last, with status and rates', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing())
    wrap(<MachinesPanel versionId={9} editable={false} plants={plants} />)
    const table = await screen.findByTestId('machinedb-table')
    const groups = within(table).getAllByRole('rowheader').map((h) => h.textContent)
    expect(groups[0]).toMatch(/^Silao Mexico/)
    expect(groups[1]).toMatch(/^USA Toccoa.*1 with an own rate/)
    expect(groups[2]).toMatch(/^Not mapped to a plant/)
    expect(within(screen.getByTestId('machine-row-3')).getByText('Scrapped')).toBeTruthy()
    expect(within(screen.getByTestId('machine-row-3')).getByText('2K turntable')).toBeTruthy()
    expect(within(screen.getByTestId('machine-row-2')).getByText('120.00 USD')).toBeTruthy()
    expect(screen.getByTestId('machinedb-last-sync').textContent).toMatch(/Last synced .* 4 machines/)
    // the unmapped MachineDB plant can be mapped
    expect(screen.getByTestId('machinedb-unmapped').textContent).toMatch(/Solingen|solingen/)
  })

  it('edits a machine rate in a draft and clears it back to the class rate', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing())
    vi.mocked(costSheetMachinesApi.setRate).mockResolvedValue(null)
    wrap(<MachinesPanel versionId={9} editable plants={plants} />)
    const input = await screen.findByLabelText('Hourly rate of P-80')
    fireEvent.change(input, { target: { value: '95,5' } })
    fireEvent.blur(input)
    await waitFor(() => expect(costSheetMachinesApi.setRate).toHaveBeenCalledWith(
      1, { version_id: 9, hourly_rate: 95.5 }))
    const own = screen.getByLabelText('Hourly rate of P-350')
    fireEvent.change(own, { target: { value: '' } })
    fireEvent.blur(own)
    await waitFor(() => expect(costSheetMachinesApi.setRate).toHaveBeenCalledWith(
      2, { version_id: 9, hourly_rate: null }))
  })

  it('says sync is off without a MachineDB connection and keeps the copy', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing({
      machinedb: { configured: false, missing: ['MACHINEDB_API_URL'], host: null },
      last_sync: { at: '2026-09-20T08:00:00', total: 4, failed_at: '2026-09-26T08:00:00',
        error: 'MachineDB is not reachable from this server' },
    }))
    wrap(<MachinesPanel versionId={9} editable={false} plants={plants} />)
    expect((await screen.findByTestId('machinedb-last-sync')).textContent)
      .toMatch(/Sync is off.*MACHINEDB_API_URL not set.*last synced copy/)
    expect(screen.getByTestId('machinedb-last-error').textContent).toMatch(/not reachable/)
    expect((screen.getByRole('button', { name: /Sync from MachineDB/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('machinedb-table')).toBeTruthy()
  })

  it('shows the sync report after a sync', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing())
    vi.mocked(costSheetMachinesApi.sync).mockResolvedValue({
      total: 4, new: 1, changed: 1, retired: 1, unmapped: 1,
      report: {
        new: [{ machinedb_id: 99, internal_name: 'P-900', machinedb_plant: 'usa', plant_id: 2 }],
        changed: [{ machinedb_id: 11, internal_name: 'P-350', machinedb_plant: 'usa', plant_id: 2,
          fields: ['clamping_force_t'] }],
        retired: [], scrapped: [{ machinedb_id: 20, internal_name: 'M-300', machinedb_plant: 'mexico', plant_id: 5 }],
        returned: [], unmapped: [{ machinedb_plant: 'solingen', count: 1, machines: ['S-500'] }], skipped: [],
      },
    })
    wrap(<MachinesPanel versionId={9} editable={false} plants={plants} />)
    fireEvent.click(await screen.findByRole('button', { name: /Sync from MachineDB/ }))
    await waitFor(() => expect(costSheetMachinesApi.sync).toHaveBeenCalledWith(false))
    const rep = await screen.findByTestId('machinedb-sync-report')
    expect(rep.textContent).toMatch(/P-900 \(USA Toccoa\)/)
    expect(rep.textContent).toMatch(/P-350: clamping force t/)
    expect(rep.textContent).toMatch(/Scrapped.*M-300/)
    expect(rep.textContent).toMatch(/solingen: 1 machine/)
    expect(rep.textContent).not.toMatch(/—/)
  })

  it('shows every mapping, saves only the touched plant and resets a hand mapping', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing({
      plant_map: {
        usa: { plant_id: 2, source: 'default' }, mexico: { plant_id: 5, source: 'setting' },
        solingen: { plant_id: null, source: 'no default for this MachineDB plant' },
        serbia: { plant_id: null, source: 'setting' },
      },
    }))
    vi.mocked(costSheetMachinesApi.setPlantMap).mockResolvedValue({})
    vi.mocked(costSheetMachinesApi.deletePlantMap).mockResolvedValue({})
    wrap(<MachinesPanel versionId={9} editable={false} plants={plants} />)
    const map = await screen.findByTestId('machinedb-plant-map')
    // in use or mapped by hand, each with its current plant and why
    expect(map.textContent).toMatch(/mexico.*mapped by hand/)
    expect(map.textContent).toMatch(/serbia.*kept unmapped by hand/)
    expect(map.textContent).toMatch(/usa.*by plant name/)
    expect((within(map).getByLabelText('mexico') as HTMLSelectElement).value).toBe('5')
    // only solingen is a problem; serbia is unmapped on purpose
    expect(screen.getByTestId('machinedb-unmapped').textContent).toMatch(/solingen have no plm2 plant/)
    expect(screen.getByTestId('machinedb-unmapped').textContent).not.toMatch(/serbia/)
    fireEvent.change(within(map).getByLabelText('solingen'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save mapping' }))
    await waitFor(() => expect(costSheetMachinesApi.setPlantMap).toHaveBeenCalledWith({ solingen: 2 }))
    fireEvent.click(within(map).getAllByRole('button', { name: 'Use default' })[0])
    await waitFor(() => expect(costSheetMachinesApi.deletePlantMap).toHaveBeenCalledWith('mexico'))
  })

  it('offers a forced sync after a refused one', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing({
      last_sync: { at: '2026-09-20T08:00:00', total: 4, failed_at: '2026-09-26T08:00:00', guard: true,
        error: 'MachineDB listed no machines while 4 are on record; nothing was changed' },
    }))
    vi.mocked(costSheetMachinesApi.sync).mockResolvedValue({
      total: 0, new: 0, changed: 0, retired: 4, unmapped: 0,
      report: { new: [], changed: [], retired: [], scrapped: [], returned: [], unmapped: [], skipped: [] },
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap(<MachinesPanel versionId={9} editable={false} plants={plants} />)
    expect((await screen.findByTestId('machinedb-last-error')).textContent).toMatch(/listed no machines/)
    fireEvent.click(screen.getByRole('button', { name: 'Sync anyway' }))
    await waitFor(() => expect(costSheetMachinesApi.sync).toHaveBeenCalledWith(true))
    confirm.mockRestore()
  })

  it('asks for the currency of an unmapped machine and edits a rate\'s currency', async () => {
    const { toast } = await import('sonner')
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing())
    vi.mocked(costSheetMachinesApi.setRate).mockResolvedValue(null)
    wrap(<MachinesPanel versionId={9} editable plants={plants} />)
    const input = await screen.findByLabelText('Hourly rate of S-500')
    const cur = screen.getByLabelText('Currency of the rate of S-500') as HTMLSelectElement
    expect(cur.value).toBe('')
    fireEvent.change(input, { target: { value: '80' } })
    fireEvent.blur(input)
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/Choose the currency/))
    expect(costSheetMachinesApi.setRate).not.toHaveBeenCalled()
    fireEvent.change(cur, { target: { value: 'EUR' } })
    fireEvent.blur(input)
    await waitFor(() => expect(costSheetMachinesApi.setRate).toHaveBeenCalledWith(
      4, { version_id: 9, hourly_rate: 80, currency: 'EUR' }))
    // an existing rate moves to another currency right away
    fireEvent.change(screen.getByLabelText('Currency of the rate of P-350'), { target: { value: 'EUR' } })
    await waitFor(() => expect(costSheetMachinesApi.setRate).toHaveBeenCalledWith(
      2, { version_id: 9, hourly_rate: 120, currency: 'EUR' }))
  })

  it('types a Silao rate in the local currency', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing({
      machines: [machine({ id: 3, internal_name: 'M-300', machinedb_plant: 'mexico', plant_id: 5,
        hourly_rate: 100, currency: 'USD', local_currency: 'MXN', local_rate: 1730,
        entered_rate: 1730, entered_currency: 'MXN', entered_in: 'local' })],
    }))
    vi.mocked(costSheetMachinesApi.setRate).mockResolvedValue(null)
    wrap(<MachinesPanel versionId={9} editable plants={plants} />)
    const local = await screen.findByLabelText('Hourly rate of M-300 in MXN') as HTMLInputElement
    expect(local.value).toBe('1730')
    expect(screen.getByTestId('machine-row-3').textContent).toMatch(/calculated/)
    fireEvent.change(local, { target: { value: '1800' } })
    fireEvent.blur(local)
    await waitFor(() => expect(costSheetMachinesApi.setRate).toHaveBeenCalledWith(
      3, { version_id: 9, entered_rate: 1800, entered_currency: 'MXN' }))
  })

  it('asks to switch a rate off the plant quote currency before an MXN rate', async () => {
    vi.mocked(costSheetMachinesApi.list).mockResolvedValue(listing({
      machines: [machine({ id: 3, internal_name: 'M-300', machinedb_plant: 'mexico', plant_id: 5,
        hourly_rate: 90, currency: 'EUR', local_currency: 'MXN', local_rate: null,
        entered_in: 'quote' })],
    }))
    vi.mocked(costSheetMachinesApi.setRate).mockResolvedValue(null)
    wrap(<MachinesPanel versionId={9} editable plants={plants} />)
    const local = await screen.findByLabelText('Hourly rate of M-300 in MXN') as HTMLInputElement
    fireEvent.change(local, { target: { value: '1800' } })
    fireEvent.blur(local)
    expect(await screen.findByText('Switch this rate to USD?')).toBeDefined()
    expect(costSheetMachinesApi.setRate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Switch to USD' }))
    await waitFor(() => expect(costSheetMachinesApi.setRate).toHaveBeenCalledWith(
      3, { version_id: 9, entered_rate: 1800, entered_currency: 'MXN', currency: 'USD' }))
  })

  it('names the status of a machine', () => {
    expect(machineStatus(machine({}))).toBe('Active')
    expect(machineStatus(machine({ active: false }))).toBe('Scrapped')
    expect(machineStatus(machine({ active: false, retired: true }))).toBe('Retired')
  })
})
