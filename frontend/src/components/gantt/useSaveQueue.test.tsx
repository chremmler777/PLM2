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
    expect(onIdMap).toHaveBeenCalledWith({ 'tmp-1': 77 })
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
      result.current.enqueue({ label: 'x', updateTasks: [{ id: 1, patch: { name: 'X' } }] }, 7)
      result.current.enqueue({ label: 'y', updateTasks: [{ id: 1, patch: { duration: 9 } }] }, 8)
    })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    await act(async () => { first.reject(new Error('nope')); await first.promise.catch(() => undefined) })
    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.any(Error), 7))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2))
    expect(result.current.display.tasks[0].name).toBe('A')
    expect(result.current.display.tasks[0].duration).toBe(9)
  })

  it('rewrites a later ChangeSet that still uses a replaced temp id (cumulative map)', async () => {
    const seen: ChangeSet[] = []
    const onChange = vi.fn((cs: ChangeSet) => { seen.push(cs); return Promise.resolve(seen.length === 1 ? { idMap: { 'tmp-1': 50, 'l-1': 60 } } : undefined) })
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
})
