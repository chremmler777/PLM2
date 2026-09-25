import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { trainingApi, type CatalogRole, type RoleState } from '../api/training'
import { useAuth } from '../contexts/AuthContext'
import { todayIso } from '../lib/format'
import TrainingSandbox from '../training/TrainingSandbox'
import TaskScreen from '../training/TaskScreen'
import { assertCurriculumCovered, TASKS, type TrainingTask } from '../training/tasks'
import type { SandboxState } from '../training/sandbox/state'
import { Notice } from '../training/ui'
import { BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT } from '../training/uiTokens'

//: One role's training, start to finish: the attestation, then the practical
//: tasks in the sandbox. Ported from TWOS pages/Onboarding.tsx.
//:
//: It runs outside AppLayout on purpose. The sidebar polls the live API (open
//: tasks, notifications), and while a sandbox adapter is installed on the
//: shared client those polls would be answered by the training copy. Outside
//: the layout there is nothing else on the page to ask the network anything.
//:
//: Two modes. Recorded: a role the user's departments owe; the attestation and
//: every attempt reach the training record. Practice (?practice=1, or any role
//: the user does not owe): the same tasks, checked in the browser, nothing
//: recorded. Practice is how a trainer or an admin walks a role.

export default function TrainingRunPage() {
  const { role = '' } = useParams()
  const [params] = useSearchParams()
  const status = useQuery({ queryKey: ['training-status'], queryFn: trainingApi.status })

  if (status.isLoading) return <Shell>{null}</Shell>
  if (status.isError || !status.data) {
    return (
      <Shell>
        <Notice tone="warn" title="Training could not be loaded">
          The system could not be reached. Refresh the page.
        </Notice>
      </Shell>
    )
  }
  const catalog = status.data.catalog.find((c) => c.role === role)
  if (!catalog) {
    return (
      <Shell>
        <Notice tone="warn" title="Unknown training role">
          There is no training called {role || 'that'}.
        </Notice>
      </Shell>
    )
  }
  const owed = status.data.roles.find((r) => r.role === role) ?? null
  const practice = params.get('practice') === '1' || owed === null
  return (
    <Shell roleLabel={catalog.label} practice={practice}>
      {practice ? (
        <PracticeFlow catalog={catalog} />
      ) : (
        <RecordedFlow role={owed!} attestationNotice={status.data.attestation_notice} />
      )}
    </Shell>
  )
}

function Shell({
  children,
  roleLabel,
  practice,
}: {
  children: React.ReactNode
  roleLabel?: string
  practice?: boolean
}) {
  const { username } = useAuth()
  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <header className="border-b border-slate-700/70 bg-slate-800/80">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 select-none items-center justify-center rounded-lg bg-gradient-to-br from-sky-500 to-blue-700 font-bold text-white">
              P
            </div>
            <div>
              <div className="text-sm font-semibold leading-none">ECR training</div>
              <div className="mt-1 text-[11px] text-slate-500">
                {roleLabel ?? 'PLM v2'}
                {practice && ' · practice, nothing is recorded'}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {username && <span className="hidden text-slate-400 sm:inline">{username}</span>}
            <Link to="/training" className="text-slate-300 hover:text-white">
              Back to Training
            </Link>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-5 px-4 py-6 pb-32">{children}</main>
    </div>
  )
}

function StepHeading({ n, of, title }: { n: number; of: number; title: string }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
        Step {n} of {of}
      </div>
      <h2 className="mt-0.5 text-xl font-semibold tracking-tight text-slate-100">{title}</h2>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recorded: attest, then the tasks the server says are owed
// ---------------------------------------------------------------------------

function RecordedFlow({ role, attestationNotice }: { role: RoleState; attestationNotice: string }) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['training-status'] })

  if (role.cleared) {
    return (
      <Notice tone="ok" title={`${role.label}: signed off`}>
        All tasks passed{role.software_version ? ` on ${role.software_version}` : ''}. Your
        record is on the Training page.
      </Notice>
    )
  }
  if (!role.attested_at) {
    return <AttestStep role={role} notice={attestationNotice} onDone={refresh} />
  }
  return <RecordedTasks role={role} onChanged={refresh} />
}

function AttestStep({
  role,
  notice,
  onDone,
}: {
  role: RoleState
  notice: string
  onDone: () => void
}) {
  const [trainerName, setTrainerName] = useState('')
  const [trainingDate, setTrainingDate] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const submit = useMutation({
    mutationFn: () =>
      trainingApi.attest({
        role: role.role,
        training_date: trainingDate,
        trainer_name: trainerName.trim(),
        confirmed: true,
      }),
    onSuccess: onDone,
    onError: (e: { response?: { data?: { detail?: string } } }) =>
      setError(e.response?.data?.detail ?? 'That could not be recorded.'),
  })
  const ready = confirmed && trainerName.trim().length > 1 && trainingDate !== ''
  const [first, ...rest] = notice.split('\n\n')

  return (
    <section className="space-y-5">
      <StepHeading n={1} of={2} title={`${role.label}: your training`} />
      <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-5">
        <h3 className="text-sm font-semibold text-slate-100">
          Training is your right, not a formality
        </h3>
        <div className="mt-2 space-y-3 text-sm leading-relaxed text-slate-300">
          <p>{first}</p>
          {rest.map((p, i) => (
            <p key={i} className="text-slate-100">
              {p}
            </p>
          ))}
        </div>
      </div>

      <div className="space-y-4 rounded-lg border border-slate-700 bg-slate-800/60 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-slate-300">
              Who trained you?
            </span>
            <input
              value={trainerName}
              onChange={(e) => setTrainerName(e.target.value)}
              placeholder="Their name"
              className={INPUT}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-slate-300">
              When was the session held?
            </span>
            <input
              type="date"
              max={todayIso()}
              value={trainingDate}
              onChange={(e) => setTrainingDate(e.target.value)}
              className={INPUT}
            />
            <span className="mt-1 block text-[11px] text-slate-500">
              The day it actually happened, not today by default.
            </span>
          </label>
        </div>
        <label className="flex items-start gap-2.5 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-slate-600"
          />
          <span>
            I confirm that this training took place, on the date above, and that the person
            named held it.
          </span>
        </label>
        {error && <p className="text-sm text-red-300">{error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={!ready || submit.isPending}
            onClick={() => {
              setError('')
              submit.mutate()
            }}
            className={BUTTON_PRIMARY}
          >
            {submit.isPending ? 'Recording...' : 'Confirm and continue'}
          </button>
          <span className="text-[12px] text-slate-500">
            Not trained yet? Leave this page and ask for your session.
          </span>
        </div>
      </div>
    </section>
  )
}

function RecordedTasks({ role, onChanged }: { role: RoleState; onChanged: () => void }) {
  const missing = useMemo(
    () => assertCurriculumCovered(role.tasks.map((t) => t.key)),
    [role.tasks],
  )
  const [started, setStarted] = useState(false)
  const next = role.tasks.find((t) => !t.passed)

  if (missing.length > 0) {
    return (
      <Notice tone="warn" title="These tasks cannot be run in this version">
        The record asks for {missing.join(', ')}, which this build does not know how to
        check. Tell whoever keeps the training records.
      </Notice>
    )
  }
  if (!started) {
    return (
      <section className="space-y-5">
        <StepHeading n={2} of={2} title={`${role.label}: practical check`} />
        {role.attestation_carried_forward && role.retrain_summary && (
          <Notice tone="info" title="The material was updated">
            <p>{role.retrain_summary}</p>
            <p className="mt-2">
              Your confirmation carries forward. Only the practical check is repeated.
            </p>
          </Notice>
        )}
        <AssessmentIntro count={role.tasks.length} onStart={() => setStarted(true)} />
      </section>
    )
  }
  if (!next) {
    return <Notice tone="ok" title="All tasks passed">Recording the result...</Notice>
  }
  return (
    <TaskRunner
      key={next.key}
      roleKey={role.role}
      roleLabel={role.label}
      task={TASKS[next.key]}
      index={role.tasks.findIndex((t) => t.key === next.key)}
      total={role.tasks.length}
      attemptsSoFar={next.attempts}
      record
      onPassed={onChanged}
    />
  )
}

function AssessmentIntro({ count, onStart }: { count: number; onStart: () => void }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-5">
      <div className="space-y-3 text-sm leading-relaxed text-slate-300">
        <p>
          What follows is a short practical check: {count}{' '}
          {count === 1 ? 'task' : 'tasks'} on the real screens, in a training copy of PLM2.
        </p>
        <p className="text-slate-100">
          Nothing you do here reaches the live system. No change, answer or deadline made in
          this exercise exists outside your own browser.
        </p>
        <p>
          You may retry as often as you like. Every attempt is recorded, to show where the
          material needs to be clearer, not to catch you out.
        </p>
      </div>
      <button type="button" onClick={onStart} className={`mt-4 ${BUTTON_PRIMARY}`}>
        Start the check
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Practice: the same tasks, nothing recorded
// ---------------------------------------------------------------------------

function PracticeFlow({ catalog }: { catalog: CatalogRole }) {
  const missing = useMemo(() => assertCurriculumCovered(catalog.tasks), [catalog.tasks])
  const [index, setIndex] = useState<number | null>(null)

  if (missing.length > 0) {
    return (
      <Notice tone="warn" title="These tasks cannot be run in this version">
        {missing.join(', ')} cannot be checked by this build.
      </Notice>
    )
  }
  if (index === null) {
    return (
      <section className="space-y-5">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
            Practice
          </div>
          <h2 className="mt-0.5 text-xl font-semibold tracking-tight text-slate-100">
            {catalog.label}: practical check
          </h2>
        </div>
        <Notice tone="info" title="Practice mode">
          The same tasks as the recorded check, checked in your browser. Nothing is recorded,
          so this does not count towards anybody's training.
        </Notice>
        <AssessmentIntro count={catalog.tasks.length} onStart={() => setIndex(0)} />
      </section>
    )
  }
  if (index >= catalog.tasks.length) {
    return (
      <div className="space-y-3">
        <Notice tone="ok" title="Practice complete">
          Every task passed. Nothing was recorded.
        </Notice>
        <button type="button" className={BUTTON_SECONDARY} onClick={() => setIndex(0)}>
          Practise again
        </button>
      </div>
    )
  }
  const key = catalog.tasks[index]
  return (
    <TaskRunner
      key={`${key}:${index}`}
      roleKey={catalog.role}
      roleLabel={catalog.label}
      task={TASKS[key]}
      index={index}
      total={catalog.tasks.length}
      attemptsSoFar={0}
      record={false}
      onPassed={() => setIndex((i) => (i ?? 0) + 1)}
    />
  )
}

// ---------------------------------------------------------------------------
// One task
// ---------------------------------------------------------------------------

function TaskRunner({
  roleKey,
  roleLabel,
  task,
  index,
  total,
  attemptsSoFar,
  record,
  onPassed,
}: {
  roleKey: string
  roleLabel: string
  task: TrainingTask
  index: number
  total: number
  attemptsSoFar: number
  record: boolean
  onPassed: () => void
}) {
  const [hint, setHint] = useState<string | null>(null)
  const [passed, setPassed] = useState(false)
  //: Bumped on every retry so the sandbox is rebuilt from the fixture. A retry
  //: against a half-mutated copy would grade the previous attempt's leftovers.
  const [attempt, setAttempt] = useState(0)
  const startedAt = useRef(Date.now())
  const stateRef = useRef<SandboxState | null>(null)

  useEffect(() => {
    startedAt.current = Date.now()
    setHint(null)
  }, [task.key, attempt])

  const check = useMutation({
    mutationFn: async () => {
      const state = stateRef.current
      if (!state) throw new Error('The training screen has not finished loading.')
      const result = task.check(state)
      if (record) {
        await trainingApi.recordAttempt({
          role: roleKey,
          task_key: task.key,
          result: result.passed ? 'passed' : 'failed',
          detail: result.passed
            ? (result.detail ?? null)
            : { hint: result.hint, ...(result.detail ?? {}), actions: state.calls.length },
          duration_seconds: Math.round((Date.now() - startedAt.current) / 1000),
        })
      }
      return result
    },
    onSuccess: (result) => {
      if (result.passed) {
        setHint(null)
        setPassed(true)
      } else setHint(result.hint ?? 'Not quite yet.')
    },
    onError: (e: Error) => setHint(e.message),
  })

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
            {roleLabel} · task {index + 1} of {total}
          </div>
          <h2 className="mt-0.5 text-xl font-semibold tracking-tight text-slate-100">
            {task.title}
          </h2>
        </div>
        {attemptsSoFar > 0 && (
          <span className="text-[12px] text-slate-500">
            {attemptsSoFar} previous {attemptsSoFar === 1 ? 'attempt' : 'attempts'}
          </span>
        )}
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4">
        <p className="text-sm leading-relaxed text-slate-100" data-testid="task-brief">
          {task.brief}
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-400">{task.why}</p>
      </div>

      {hint && (
        <div
          role="alert"
          className="rounded-lg border-2 border-amber-600/60 bg-amber-950/30 p-4"
        >
          <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-400">
            Not yet
          </div>
          <p className="mt-1 text-sm text-slate-100">{hint}</p>
          <button
            type="button"
            onClick={() => setAttempt((a) => a + 1)}
            className={`mt-3 ${BUTTON_SECONDARY}`}
          >
            Start this task over
          </button>
        </div>
      )}

      {passed ? (
        <Notice tone="ok" title="Passed">
          <button type="button" onClick={onPassed} className={`mt-2 ${BUTTON_PRIMARY}`}>
            {index + 1 < total ? 'Next task' : 'Finish'}
          </button>
        </Notice>
      ) : (
        <TrainingSandbox resetKey={`${task.key}:${attempt}`}>
          {(state) => {
            stateRef.current = state
            return (
              <>
                <SandboxGaps state={state} />
                <TaskScreen screen={task.screen} />
              </>
            )
          }}
        </TrainingSandbox>
      )}

      {/* Fixed, and above the app's modal layer (z-50): the start form is a
          modal, and the trainee must be able to check without closing it. */}
      {!passed && (
        <div className="fixed inset-x-0 bottom-0 z-[60] border-t border-slate-700 bg-slate-900/95 backdrop-blur">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0 truncate text-sm text-slate-400">
              <span className="text-slate-200">{task.title}</span>
              {!record && <span className="ml-2 text-amber-300/80">practice</span>}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => setAttempt((a) => a + 1)}
                className={BUTTON_SECONDARY}
              >
                Start over
              </button>
              <button
                type="button"
                data-testid="check-work"
                disabled={check.isPending}
                onClick={() => check.mutate()}
                className={BUTTON_PRIMARY}
              >
                {check.isPending ? 'Checking...' : 'Check my work'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

/** Requests the fixture could not answer: a gap in the training copy, said out loud. */
function SandboxGaps({ state }: { state: SandboxState }) {
  const [, force] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => force((n) => n + 1), 1000)
    return () => window.clearInterval(t)
  }, [])
  if (state.misses.length === 0) return null
  return (
    <div className="mb-3 rounded border border-red-700/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
      The training copy could not answer:{' '}
      {state.misses.map((m) => `${m.method.toUpperCase()} ${m.url}`).join(', ')}. This is a
      gap in the training fixture, not something you did. Tell whoever keeps the training.
    </div>
  )
}
