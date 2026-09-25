import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useSaveQueue, type SaveQueueOptions } from './useSaveQueue'
import type { ApplyResult, ChangeSet, GanttModel } from './engine/types'

const model = (): GanttModel => ({ tasks: [{ id: 1, name: 'A', start: '2026-10-05', duration: 3 }], links: [] })
const deferred = <T,>() => {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const setup = (opts: SaveQueueOptions, base = model()) =>
  renderHook(({ b, o }) => useSaveQueue(b, o), { initialProps: { b: base, o: opts } })

describe('useSaveQueue', () => {
  it('shows a change at once, before the save answers', async () => {
    const d = deferred<void>()
    const { result } = setup({ onChange: () => d.promise })
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'B' } }] }))
    expect(result.current.display.tasks[0].name).toBe('B')
    await waitFor(() => expect(result.current.saving).toBe(true))
    await act(async () => { d.resolve(); await d.promise })
  })

  it('sends one ChangeSet at a time, in order', async () => {
    const calls: ChangeSet[] = []
    const ds = [deferred<void>(), deferred<void>()]
    const onChange = vi.fn((cs: ChangeSet) => { calls.push(cs); return ds[calls.length - 1].promise })
    const { result } = setup({ onChange })
    act(() => {
      result.current.enqueue({ label: 'one', updateTasks: [{ id: 1, patch: { duration: 4 } }] })
      result.current.enqueue({ label: 'two', updateTasks: [{ id: 1, patch: { duration: 5 } }] })
    })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect(calls[0].label).toBe('one')
    expect(result.current.queueLength).toBe(2)
    await act(async () => { ds[0].resolve(); await ds[0].promise })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(calls[1].label).toBe('two')
    await act(async () => { ds[1].resolve(); await ds[1].promise })
    await waitFor(() => expect(result.current.saving).toBe(false))
    expect(result.current.display.tasks[0].duration).toBe(5)
  })

  it('remaps temporary ids of queued items and reports the map', async () => {
    const first = deferred<ApplyResult>()
    const seen: ChangeSet[] = []
    const onIdMap = vi.fn()
    const onChange = vi.fn((cs: ChangeSet) => { seen.push(cs); return seen.length === 1 ? first.promise : Promise.resolve() })
    const { result } = setup({ onChange, onIdMap })
    act(() => {
      result.current.enqueue({ addTasks: [{ id: 'tmp-1', name: 'New', start: '2026-10-05', duration: 1 }] })
      result.current.enqueue({ updateTasks: [{ id: 'tmp-1', patch: { name: 'Renamed' } }] })
    })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    await act(async () => { first.resolve({ idMap: { 'tmp-1': 77 } }); await first.promise })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(onIdMap).toHaveBeenCalledWith({ 'tmp-1': 77 }, {})
    expect(seen[1].updateTasks![0].id).toBe(77)
  })

  it('drops a saved change once the host model shows it', async () => {
    const { result, rerender } = setup({ onChange: () => Promise.resolve() })
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'Saved' } }] }))
    await waitFor(() => expect(result.current.saving).toBe(false))
    expect(result.current.display.tasks[0].name).toBe('Saved')
    const server: GanttModel = { tasks: [{ id: 1, name: 'Saved', start: '2026-10-05', duration: 3 }], links: [] }
    rerender({ b: server, o: { onChange: () => Promise.resolve() } })
    await waitFor(() => expect(result.current.display).toBe(server))
  })

  it('keeps a saved change over a stale refetch until it settles', async () => {
    const opts = { onChange: () => Promise.resolve(), settleMs: 80 }
    const { result, rerender } = setup(opts)
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'Saved' } }] }))
    await waitFor(() => expect(result.current.saving).toBe(false))
    // A refetch that started before the save answers with the old name.
    const stale: GanttModel = { tasks: [{ id: 1, name: 'A', start: '2026-10-05', duration: 3 }], links: [] }
    rerender({ b: stale, o: opts })
    expect(result.current.display.tasks[0].name).toBe('Saved')
    await waitFor(() => expect(result.current.display.tasks[0].name).toBe('A'), { timeout: 1000 })
  })

  it('rolls back only the refused change, reports it with its tag, and sends the next one', async () => {
    const first = deferred<void>()
    const onError = vi.fn()
    const onChange = vi.fn((cs: ChangeSet) => (cs.label === 'x' ? first.promise : Promise.resolve()))
    const { result } = setup({ onChange, onError })
    act(() => {
      result.current.enqueue({ label: 'x', updateTasks: [{ id: 1, patch: { name: 'X' } }] }, { entry: 7, dir: 'do' })
      result.current.enqueue({ label: 'y', updateTasks: [{ id: 1, patch: { duration: 9 } }] }, { entry: 8, dir: 'do' })
    })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    await act(async () => { first.reject(new Error('nope')); await first.promise.catch(() => undefined) })
    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.any(Error), { entry: 7, dir: 'do' }, expect.any(Number)))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(result.current.display.tasks[0].name).toBe('A')
    expect(result.current.display.tasks[0].duration).toBe(9)
  })

  it('rewrites a later ChangeSet that still uses a replaced temp id (cumulative map)', async () => {
    const seen: ChangeSet[] = []
    const onChange = vi.fn((cs: ChangeSet) => { seen.push(cs); return Promise.resolve(seen.length === 1 ? { idMap: { 'tmp-1': 50 }, linkIdMap: { 'l-1': 60 } } : undefined) })
    const { result } = setup({ onChange })
    act(() => result.current.enqueue({ addTasks: [{ id: 'tmp-1', name: 'N', start: '2026-10-05', duration: 1 }], addLinks: [{ id: 'l-1', from: 1, to: 'tmp-1', type: 'FS', lagDays: 0 }] }))
    await waitFor(() => expect(result.current.saving).toBe(false))
    // Built from a view that still showed the temp ids.
    act(() => result.current.enqueue({ updateTasks: [{ id: 'tmp-1', patch: { name: 'M' } }], updateLinks: [{ id: 'l-1', patch: { lagDays: 2 } }] }))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(seen[1].updateTasks![0].id).toBe(50)
    expect(seen[1].updateLinks![0].id).toBe(60)
    expect(result.current.resolveId('tmp-1')).toBe(50)
  })

  it('marks the tasks of unsaved changes as pending', async () => {
    const d = deferred<void>()
    const { result } = setup({ onChange: () => d.promise })
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'Z' } }] }))
    expect(result.current.pendingIds.has('1')).toBe(true)
    await act(async () => { d.resolve(); await d.promise })
    await waitFor(() => expect(result.current.pendingIds.size).toBe(0))
  })

  it('works without an onChange (local only)', async () => {
    const { result } = setup({})
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { duration: 9 } }] }))
    await waitFor(() => expect(result.current.saving).toBe(false))
    expect(result.current.display.tasks[0].duration).toBe(9)
  })

  it('keeps task and link id maps apart and never keeps numeric keys for later changes', async () => {
    const seen: ChangeSet[] = []
    const onIdMap = vi.fn()
    const onChange = vi.fn((cs: ChangeSet) => { seen.push(cs); return Promise.resolve(seen.length === 1 ? { idMap: { 'tmp-1': 50, 5: 60 }, linkIdMap: { 1: 3, 'l-1': 9 } } : undefined) })
    const { result } = setup({ onChange, onIdMap })
    act(() => result.current.enqueue({ addTasks: [{ id: 'tmp-1', name: 'N', start: '2026-10-05', duration: 1 }] }))
    await waitFor(() => expect(result.current.saving).toBe(false))
    expect(onIdMap).toHaveBeenCalledWith({ 'tmp-1': 50, 5: 60 }, { 1: 3, 'l-1': 9 })
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'x' } }, { id: 5, patch: { name: 'y' } }, { id: 'tmp-1', patch: { name: 'z' } }], removeLinks: ['l-1', 1] }))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(seen[1].updateTasks!.map((u) => u.id)).toEqual([1, 5, 50])
    expect(seen[1].removeLinks).toEqual([9, 1])
  })

  it('skips a ChangeSet that is empty once remapped', async () => {
    const onChange = vi.fn(() => Promise.resolve())
    const { result } = setup({ onChange })
    act(() => result.current.enqueue({ label: 'nothing' }))
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'B' } }] }))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    expect((onChange.mock.calls[0] as unknown as [ChangeSet])[0].updateTasks).toBeTruthy()
  })

  it('drops the queued undo / redo saves of a refused original change', async () => {
    const first = deferred<void>()
    const onChange = vi.fn((cs: ChangeSet) => (cs.label === 'add' ? first.promise : Promise.resolve()))
    const onError = vi.fn(() => 3)
    const { result } = setup({ onChange, onError })
    act(() => {
      result.current.enqueue({ label: 'add', addTasks: [{ id: 'tmp-z', name: 'Z', start: '2026-10-05', duration: 1 }] }, { entry: 3, dir: 'do' })
      result.current.enqueue({ label: 'undo', updateTasks: [{ id: 1, patch: { name: 'other' } }] }, { entry: 3, dir: 'undo' })
      result.current.enqueue({ label: 'keep', updateTasks: [{ id: 1, patch: { duration: 7 } }] }, { entry: 4, dir: 'do' })
    })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    await act(async () => { first.reject(new Error('no')); await first.promise.catch(() => undefined) })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect((onChange.mock.calls[1] as unknown as [ChangeSet])[0].label).toBe('keep')
  })

  describe('the server answer (review 4b93d732 #11)', () => {
    const L12 = { id: 'L', from: 1, to: 2, type: 'FS' as const, lagDays: 0 }
    const two = (): GanttModel => ({
      tasks: [{ id: 1, name: 'A', start: '2026-10-05', duration: 3 }, { id: 2, name: 'B', start: '2026-10-08', duration: 2 }], links: [L12],
    })

    it('reports the tasks the server moved on its own and shows its answer without waiting', async () => {
      const server: GanttModel = {
        tasks: [{ id: 1, name: 'A', start: '2026-10-05', duration: 5 }, { id: 2, name: 'B', start: '2026-10-12', duration: 2 }], links: [L12],
      }
      const onServerMoves = vi.fn()
      const onChange = vi.fn(async () => ({ server }))
      const { result, rerender } = setup({ onChange, onServerMoves, settleMs: 60_000 }, two())
      act(() => { result.current.enqueue({ updateTasks: [{ id: 1, patch: { duration: 5 } }] }, { entry: 1, dir: 'do' }) })
      await waitFor(() => expect(onServerMoves).toHaveBeenCalled())
      expect(onServerMoves.mock.calls[0]).toEqual([{ entry: 1, dir: 'do' },
        [{ id: 2, from: { start: '2026-10-08', duration: 2 }, to: { start: '2026-10-12', duration: 2 } }]])
      // the host now shows a server answer that differs from the optimistic view
      // for the edited task too: it wins at once, not after settleMs
      const other: GanttModel = { tasks: [{ ...server.tasks[0], duration: 6 }, server.tasks[1]], links: [L12] }
      rerender({ b: other, o: { onChange, onServerMoves, settleMs: 60_000 } })
      await waitFor(() => expect(result.current.display.tasks[0].duration).toBe(6))
    })

    it('drops the overlay at once when the host already shows the answer', async () => {
      const server = two()
      server.tasks[0] = { ...server.tasks[0], duration: 4 }
      let rer: ((p: { b: GanttModel; o: SaveQueueOptions }) => void) | null = null
      const opts: SaveQueueOptions = {
        settleMs: 60_000,
        onChange: async () => { rer!({ b: server, o: opts }); return { server } },
      }
      const { result, rerender } = setup(opts, two())
      rer = rerender
      act(() => { result.current.enqueue({ updateTasks: [{ id: 1, patch: { duration: 5 } }] }) })
      await waitFor(() => expect(result.current.saving).toBe(false))
      expect(result.current.display.tasks[0].duration).toBe(4)
    })
  
    it('never counts summaries (roll-ups), unreachable tasks or edits from elsewhere as server moves (review ee43fb8c #1, #2)', async () => {
      const { serverMoves } = await import('./useSaveQueue')
      const before: GanttModel = {
        tasks: [
          { id: 'S', name: 'S', start: '2026-10-05', duration: 5 },
          { id: 1, name: 'A', start: '2026-10-05', duration: 3, parentId: 'S' },
          { id: 2, name: 'B', start: '2026-10-08', duration: 2, parentId: 'S' },
          { id: 3, name: 'C', start: '2026-10-05', duration: 1 },
          { id: 4, name: 'D', start: '2026-10-20', duration: 1 },
        ],
        links: [{ id: 'L', from: 1, to: 2, type: 'FS', lagDays: 0 }, { id: 'M', from: 'S', to: 4, type: 'FS', lagDays: 0 }],
      }
      const server: GanttModel = {
        tasks: [
          { id: 'S', name: 'S', start: '2026-10-05', duration: 8 },
          { id: 1, name: 'A', start: '2026-10-05', duration: 5, parentId: 'S' },
          { id: 2, name: 'B', start: '2026-10-10', duration: 2, parentId: 'S' },
          { id: 3, name: 'C', start: '2026-10-09', duration: 1 }, // someone else moved it
          { id: 4, name: 'D', start: '2026-10-21', duration: 1 },
        ],
        links: before.links,
      }
      const moves = serverMoves(before, { updateTasks: [{ id: 1, patch: { duration: 5 } }] }, server)
      expect(moves.map((m) => m.id)).toEqual([2, 4])
    })
  })
})
