import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import client from '../api/client'
import TrainingSandbox from './TrainingSandbox'
import TaskScreen from './TaskScreen'
import { sandboxIsOpen } from './sandbox/containment'
import type { SandboxState } from './sandbox/state'
import { SEED } from './sandbox/state'
import { TASKS } from './tasks'

//: The mechanism end to end: the real screen, the real shared client, the
//: training adapter underneath. Nothing is mocked but the network, and the
//: network is never reached (a request that tried would throw).

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

function mount(screenFor: Parameters<typeof TaskScreen>[0]['screen']) {
  let state: SandboxState | null = null
  const before = client.defaults.adapter
  const view = render(
    <TrainingSandbox resetKey="t">
      {(s) => {
        state = s
        return <TaskScreen screen={screenFor} />
      }}
    </TrainingSandbox>,
  )
  return { view, before, state: () => state! }
}

describe('TrainingSandbox with a real screen', () => {
  it('answers a checklist row on the real assessment form, and the task passes', async () => {
    const { state } = mount({ kind: 'assessment', department: 'Tool Engineer' })
    const yes = await screen.findByTestId('check-yes-modification_internal')
    expect(sandboxIsOpen()).toBe(true)
    fireEvent.click(yes)
    fireEvent.change(await screen.findByTestId('check-remark-modification_internal'), {
      target: { value: 'Modify the clip tower insert in house' },
    })
    // The form autosaves the draft to the server after a pause.
    await waitFor(() => expect(state().drafts[SEED.assessmentFor['Tool Engineer']]).toBeTruthy(), {
      timeout: 3000,
    })
    expect(TASKS.eng_answer_checklist_row.check(state()).passed).toBe(true)
    expect(state().misses).toEqual([])
  })

  it('opens the real start form against the fixture', async () => {
    const { state } = mount({ kind: 'start-change' })
    fireEvent.click(await screen.findByTestId('start-change'))
    expect(await screen.findByRole('option', { name: /T100/ })).toBeTruthy()
    expect(state().misses).toEqual([])
  })

  it('puts the live adapter back when it unmounts', async () => {
    const { view, before } = mount({ kind: 'change-status', changeId: SEED.changeCaptured })
    await screen.findByText('CR-TRAIN-0001')
    expect(client.defaults.adapter).not.toBe(before)
    view.unmount()
    expect(client.defaults.adapter).toBe(before)
    expect(sandboxIsOpen()).toBe(false)
  })
})
