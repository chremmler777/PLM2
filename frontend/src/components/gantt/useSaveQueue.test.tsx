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

  it('keeps a saved change applied until the host passes a new model', async () => {
    const { result, rerender } = setup({ onChange: () => Promise.resolve() })
    act(() => result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'Saved' } }] }))
    await waitFor(() => expect(result.current.saving).toBe(false))
    expect(result.current.display.tasks[0].name).toBe('Saved')
    const server: GanttModel = { tasks: [{ id: 1, name: 'Server', start: '2026-10-05', duration: 3 }], links: [] }
    rerender({ b: server, o: { onChange: () => Promise.resolve() } })
    await waitFor(() => expect(result.current.display.tasks[0].name).toBe('Server'))
  })

  it('drops the whole queue and reports an error', async () => {
    const first = deferred<void>()
    const onError = vi.fn()
    const onChange = vi.fn(() => first.promise)
    const { result } = setup({ onChange, onError })
    act(() => {
      result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'X' } }] })
      result.current.enqueue({ updateTasks: [{ id: 1, patch: { name: 'Y' } }] })
    })
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
    await act(async () => { first.reject(new Error('nope')); await first.promise.catch(() => undefined) })
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(result.current.display.tasks[0].name).toBe('A')
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(result.current.saving).toBe(false)
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
