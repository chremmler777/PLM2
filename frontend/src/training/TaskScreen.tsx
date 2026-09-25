import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, UNSAFE_LocationContext, useParams } from 'react-router-dom'
import { changesApi } from '../api/changes'
import StartChangeButton from '../components/changes/StartChangeButton'
import StartChangeModal from '../components/changes/StartChangeModal'
import { PriorityEditor } from '../components/changes/PriorityEditor'
import { DeadlineEditor } from '../components/changes/DeadlineEditor'
import AssessmentSubmitForm from '../components/changes/AssessmentSubmitForm'
import type { ChangeDetail } from '../types/change'
import { SEED } from './sandbox/state'
import type { Screen } from './tasks'

//: The real screens, mounted inside the sandbox (ported from TWOS).
//:
//: These are the components the live app renders: the start form, the status
//: card's editors, the department's assessment form. Not copies. If the start
//: form gains a required field tomorrow, the trainee meets it here the same
//: day, without anybody having to remember to update a training mock.
//:
//: Everything runs inside its own in-memory router. The start form navigates
//: to the new change when it is done; in the live app that is the change page,
//: here it must not leave the training run, so the navigation lands on a
//: sandbox route that says what happened instead.

export default function TaskScreen({ screen }: { screen: Screen }) {
  return (
    // A router inside the app's router: react-router refuses that unless the
    // outer location context is hidden. Scoped to the sandbox only.
    //
    // No supported API does this in react-router 6.30: every router
    // (MemoryRouter, and RouterProvider over createMemoryRouter) renders
    // <Router>, which asserts !useInRouterContext() in production too, and
    // there is no public way to leave the outer context. A separate React
    // root (createRoot) would drop the app's providers the real screens need.
    // Revisit on the move to react-router 7; TrainingSandbox.test.tsx mounts
    // the real start form through this and fails if the export disappears.
    <UNSAFE_LocationContext.Provider value={null as never}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<ScreenBody screen={screen} />} />
          <Route path="/changes/:id" element={<ChangeOpened />} />
          <Route path="*" element={<LeftTheExercise />} />
        </Routes>
      </MemoryRouter>
    </UNSAFE_LocationContext.Provider>
  )
}

function ScreenBody({ screen }: { screen: Screen }) {
  if (screen.kind === 'start-change') return <StartChangeScreen />
  if (screen.kind === 'change-status') return <ChangeStatusScreen changeId={screen.changeId} />
  return <AssessmentScreen department={screen.department} />
}

// --- Sales: the Changes list's entry point, and the real start form ---------

function StartChangeScreen() {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-100">Changes</h3>
          <p className="text-xs text-slate-400">Every change request, in every project.</p>
        </div>
        <StartChangeButton label="+ New change request" onClick={() => setOpen(true)} />
      </div>
      <p className="text-sm text-slate-400">
        The training copy holds one project (T100 Training Atlas) and its parts.
      </p>
      <StartChangeModal open={open} onClose={() => setOpen(false)} />
    </div>
  )
}

function ChangeOpened() {
  const { id } = useParams()
  const { data } = useQuery({
    queryKey: ['change', Number(id)],
    queryFn: () => changesApi.get(Number(id)),
  })
  return (
    <div className="rounded-lg border border-emerald-700/50 bg-emerald-950/30 p-4 text-sm text-emerald-100">
      <div className="font-semibold">Change request started{data ? `: ${data.change_number}` : ''}</div>
      {data && <div className="mt-1 text-emerald-200/80">{data.title}</div>}
      <p className="mt-2 text-emerald-200/70">
        In the live system this opens the change page. Check your work below.
      </p>
    </div>
  )
}

function LeftTheExercise() {
  return (
    <p className="text-sm text-slate-400">
      That link leads out of the exercise. Start the task over to return.
    </p>
  )
}

// --- Project Management: the status card's editors ---------------------------

function useChange(changeId: number) {
  return useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
  })
}

function ChangeHeader({ change }: { change: ChangeDetail }) {
  return (
    <div>
      <div className="font-mono text-xs text-slate-400">{change.change_number}</div>
      <h3 className="text-base font-semibold text-slate-100">{change.title}</h3>
      {change.reason && <p className="mt-1 text-sm text-slate-400">{change.reason}</p>}
    </div>
  )
}

function ChangeStatusScreen({ changeId }: { changeId: number }) {
  const { data: change } = useChange(changeId)
  if (!change) return null
  return (
    <div className="space-y-4">
      <ChangeHeader change={change} />
      <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4 space-y-3 text-sm">
        <div className="text-xs uppercase tracking-wide text-slate-400">Status</div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-slate-400 w-28">Priority</span>
          <PriorityEditor change={change} canEdit />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-slate-400 w-28">Quote deadline</span>
          <DeadlineEditor change={change} />
        </div>
      </div>
    </div>
  )
}

// --- Departments: the real assessment form -----------------------------------

function AssessmentScreen({ department }: { department: string }) {
  const { data: change } = useChange(SEED.changeInAssessment)
  const [submitted, setSubmitted] = useState(false)
  if (!change) return null
  const departmentId = SEED.departments[department]
  const row = change.assessments.find((a) => a.department_id === departmentId)
  return (
    <div className="space-y-4">
      <ChangeHeader change={change} />
      <div className="space-y-2">
        <div className="text-xs uppercase tracking-wide text-slate-400">
          Assessment: {department}
        </div>
        {submitted || row?.submitted_at ? (
          <div className="rounded-lg border border-emerald-700/50 bg-emerald-950/30 p-3 text-sm text-emerald-100">
            {department} assessment submitted. Check your work below.
          </div>
        ) : (
          <AssessmentSubmitForm
            changeId={change.id}
            departmentId={departmentId}
            departmentName={department}
            assessmentId={row?.id}
            serverDraft={(row?.details as Record<string, unknown> | null) ?? null}
            showEffort={false}
            onDone={() => setSubmitted(true)}
          />
        )}
      </div>
    </div>
  )
}
