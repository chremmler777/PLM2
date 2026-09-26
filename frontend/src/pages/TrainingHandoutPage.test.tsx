import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { TrainingStatus } from '../api/training'
import TrainingHandoutPage from './TrainingHandoutPage'

const STATUS: TrainingStatus = {
  user_id: 1,
  software_version: 'v-test',
  cleared: false,
  has_roles: true,
  roles: [],
  catalog: [
    {
      role: 'engineering',
      label: 'Engineers',
      departments: ['Development', 'Tool Engineer'],
      code_version: 1,
      required_version: 1,
      tasks: ['eng_answer_checklist_row', 'eng_submit_assessment'],
    },
  ],
  gate_enabled: false,
  gate_source: 'default',
  can_manage: false,
  acting_as: null,
  practice_only: false,
  attestation_notice: '',
  assessment_notice: '',
}

vi.mock('../api/training', () => ({
  trainingApi: { status: () => Promise.resolve(STATUS) },
}))

afterEach(cleanup)

function mount(path: string) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/training/handout/:role" element={<TrainingHandoutPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TrainingHandoutPage', () => {
  it('prints the one-page handout, the check with what is coming, and no chapters by default', async () => {
    mount('/training/handout/engineering')
    const one = await screen.findByTestId('one-page-handout')
    expect(one.textContent).toContain('Department specifics')
    expect(one.textContent).toContain('Cycle time: changed (new value entered) or confirmed unchanged')
    expect(screen.getByText('Answer a checklist row.')).toBeTruthy()
    const coming = screen.getByTestId('coming-tasks')
    expect(coming.textContent).toContain('Coming later')
    expect(coming.querySelector('button, a')).toBeNull()
    expect(document.getElementById('eng-checklist')).toBeNull()
  })

  it('appends the role chapters with "With the full chapters"', async () => {
    mount('/training/handout/engineering?full=1')
    await screen.findByTestId('one-page-handout')
    expect(document.getElementById('eng-checklist')).not.toBeNull()
    // Every slot has its screenshot now: the chapters print the pictures.
    const imgs = [...document.querySelectorAll('img')].map((i) => i.getAttribute('src') ?? '')
    expect(imgs.some((src) => src.endsWith('manual/eng-checklist.png'))).toBe(true)
  })
})
