import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ArrowRight, Check } from 'lucide-react'
import {
  rosterCsvUrl,
  trainingApi,
  type CatalogRole,
  type RoleState,
  type TrainingStatus,
} from '../api/training'
import { useAuth } from '../contexts/AuthContext'
import { formatDate, formatDateTime, todayIso } from '../lib/format'
import { toastError } from '../lib/apiError'
import ConfirmDialog from '../components/common/ConfirmDialog'
import DateInput from '../components/gantt/DateInput'
import { CHAPTERS, type ManualChapter } from '../training/manual/chapters'
import { TASKS } from '../training/tasks'
import { Notice, StagePill } from '../training/ui'
import { BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT, stageOf } from '../training/uiTokens'

//: The Training page: your own record, the manual, and (for admin, Quality and
//: Project Management) the records everybody else's training is kept in.
//: The practical tasks themselves run on a page of their own, outside the
//: layout (TrainingRunPage), because the sandbox must not share the page with
//: anything that asks the live API.

type Tab = 'mine' | 'manual' | 'records'

export default function TrainingPage() {
  const [params, setParams] = useSearchParams()
  const status = useQuery({ queryKey: ['training-status'], queryFn: trainingApi.status })
  const canManage = status.data?.can_manage ?? false
  const tab: Tab =
    params.get('tab') === 'manual'
      ? 'manual'
      : params.get('tab') === 'records' && canManage
        ? 'records'
        : 'mine'
  const setTab = (t: Tab) => setParams(t === 'mine' ? {} : { tab: t }, { replace: true })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400">
            ECR process
          </div>
          <h1 className="mt-0.5 text-2xl font-semibold tracking-tight text-slate-100">Training</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            What your role does in a change, a short practical check on the real screens, and
            the record of who was trained on what.
          </p>
        </div>
        {status.data && (
          <span className="rounded-full border border-slate-700 px-2.5 py-1 font-mono text-[11px] text-slate-400">
            {status.data.software_version}
          </span>
        )}
      </header>

      <nav className="flex gap-1 border-b border-slate-700/70" role="tablist">
        {(
          [
            ['mine', 'My training'],
            ['manual', 'Manual'],
            ...(canManage ? [['records', 'Records'] as const] : []),
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
              tab === key
                ? 'border-sky-400 text-sky-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      {status.isLoading && <p className="text-sm text-slate-400">Loading…</p>}
      {status.isError && (
        <Notice tone="warn" title="Training could not be loaded">
          The system could not be reached. Refresh the page.
        </Notice>
      )}
      {status.data && tab === 'mine' && <MyTraining data={status.data} />}
      {status.data && tab === 'manual' && <ManualView data={status.data} />}
      {status.data && tab === 'records' && canManage && <Records data={status.data} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// My training
// ---------------------------------------------------------------------------

function GateLine({ data }: { data: TrainingStatus }) {
  return data.gate_enabled ? (
    <Notice tone="warn" title="Training is required">
      Change actions are held until the training for your roles is signed off.
    </Notice>
  ) : (
    <p className="text-[13px] text-slate-400">
      Training is recorded for the audit. It does not block any change action.
    </p>
  )
}

function MyTraining({ data }: { data: TrainingStatus }) {
  const owed = new Set(data.roles.map((r) => r.role))
  const others = data.catalog.filter((c) => !owed.has(c.role))
  return (
    <div className="space-y-6">
      <GateLine data={data} />
      {data.acting_as && (
        <Notice tone="info" title={`Acting as ${data.acting_as}: practice only`}>
          You see the training this department owes and can walk its tasks. Nothing is
          recorded, for you or for the department. Stop acting as the department to record
          your own training.
        </Notice>
      )}
      {data.has_roles ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.roles.map((r) => (
            <RoleCard key={r.role} role={r} practiceOnly={data.practice_only} />
          ))}
        </div>
      ) : (
        <Notice tone="info" title="No training is owed by your departments">
          Training follows your department (Sales, Project Manager, the engineering
          departments, Scheduling, Quality, Finance). You can still practice any role below;
          nothing is recorded.
        </Notice>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-200">Practice a role</h2>
        <p className="text-[13px] text-slate-400">
          The same tasks, checked in your browser, nothing recorded. For trainers, and for
          anybody who wants another go.
        </p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {[...data.roles.map((r) => data.catalog.find((c) => c.role === r.role)!), ...others].map(
            (c) => (
              <PracticeRow key={c.role} role={c} />
            ),
          )}
        </div>
      </section>
    </div>
  )
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-200">{children}</dd>
    </div>
  )
}

function RoleCard({ role, practiceOnly }: { role: RoleState; practiceOnly: boolean }) {
  const stage = stageOf(role)
  const passed = role.tasks.filter((t) => t.passed).length
  const action = practiceOnly
    ? 'Practice'
    : stage === 'signed_off'
      ? null
      : stage === 'not_started'
        ? 'Confirm your training'
        : stage === 'retrain_due'
          ? 'Take the new check'
          : 'Continue the check'
  return (
    <article
      data-testid={`role-card-${role.role}`}
      className="space-y-4 rounded-lg border border-slate-700 bg-slate-800/60 p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-100">{role.label}</h3>
          <p className="mt-0.5 text-[12px] text-slate-400">{role.departments.join(', ')}</p>
        </div>
        <StagePill stage={stage} />
      </div>
      {role.retrain_due && role.retrain_summary && (
        <Notice tone="warn" title={`Version ${role.required_version}, published ${formatDate(role.retrain_since)}`}>
          {role.retrain_summary}
        </Notice>
      )}
      {!role.cleared && role.open_reason && !role.retrain_due && (
        <p className="text-sm text-slate-400">{role.open_reason}</p>
      )}
      <dl className="grid grid-cols-2 gap-3">
        <Fact label="Trained on">{formatDate(role.training_date)}</Fact>
        <Fact label="Trainer">{role.trainer_name ?? '-'}</Fact>
        <Fact label="Tasks passed">{formatDateTime(role.tasks_passed_at)}</Fact>
        <Fact label="Software version">{role.software_version ?? '-'}</Fact>
      </dl>
      <div>
        <div className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-400">
          Practical tasks ({passed} of {role.tasks.length}) · version {role.required_version}
        </div>
        <ul className="space-y-1">
          {role.tasks.map((t) => (
            <li key={t.key} className="flex items-center gap-2 text-sm">
              <span
                className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
                  t.passed ? 'bg-emerald-600 text-white' : 'border border-slate-600'
                }`}
                aria-hidden
              >
                {t.passed && <Check size={11} strokeWidth={3} />}
              </span>
              <span className="sr-only">{t.passed ? 'Passed:' : 'Open:'}</span>
              <span className={t.passed ? 'text-slate-300' : 'text-slate-400'}>
                {TASKS[t.key]?.title ?? t.key}
              </span>
              {t.attempts > 0 && (
                <span className="text-[11px] text-slate-400">
                  {t.attempts} {t.attempts === 1 ? 'attempt' : 'attempts'}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {action && (
          <Link
            to={`/training/run/${role.role}${practiceOnly ? '?practice=1' : ''}`}
            className={BUTTON_PRIMARY}
          >
            {action}
          </Link>
        )}
        <Link to={`/training/handout/${role.role}`} className={BUTTON_SECONDARY}>
          Printable handout
        </Link>
      </div>
    </article>
  )
}

function PracticeRow({ role }: { role: CatalogRole }) {
  return (
    <Link
      to={`/training/run/${role.role}?practice=1`}
      className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2.5 text-sm text-slate-300 transition hover:border-slate-500 hover:bg-slate-800/60"
    >
      <span>
        <span className="font-medium text-slate-100">{role.label}</span>
        <span className="ml-2 text-[12px] text-slate-400">
          {role.tasks.length} {role.tasks.length === 1 ? 'task' : 'tasks'}
        </span>
      </span>
      <ArrowRight aria-hidden="true" size={16} className="shrink-0 text-slate-400" />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Manual
// ---------------------------------------------------------------------------

function ManualView({ data }: { data: TrainingStatus }) {
  const mineRoles = data.roles.map((r) => r.role)
  const mine = useMemo(
    () =>
      new Set(
        CHAPTERS.filter((c) => c.roles && c.roles.some((r) => mineRoles.includes(r))).map(
          (c) => c.id,
        ),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mineRoles.join(',')],
  )
  return (
    <div className="grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)] lg:items-start">
      <nav className="sticky top-6 hidden lg:block">
        <ul className="space-y-3 text-sm">
          {CHAPTERS.map((c) => (
            <li key={c.id}>
              <a
                href={`#${c.id}`}
                className="flex items-baseline gap-2 font-medium text-slate-200 hover:text-white"
              >
                <span className="font-mono text-[11px] text-slate-400">{c.number}</span>
                <span className="min-w-0">{c.title}</span>
                {mine.has(c.id) && <YoursTag />}
              </a>
            </li>
          ))}
        </ul>
        <div className="mt-6 space-y-1 border-t border-slate-700/70 pt-4 text-[13px]">
          <div className="text-[11px] uppercase tracking-wide text-slate-400">Handouts</div>
          {data.catalog.map((c) => (
            <Link
              key={c.role}
              to={`/training/handout/${c.role}`}
              className="block text-slate-400 hover:text-slate-200"
            >
              {c.label}
            </Link>
          ))}
        </div>
      </nav>
      <div className="min-w-0 max-w-3xl space-y-12">
        {CHAPTERS.map((c) => (
          <Chapter key={c.id} chapter={c} mine={mine.has(c.id)} />
        ))}
      </div>
    </div>
  )
}

function YoursTag() {
  return (
    <span className="shrink-0 rounded-full bg-sky-500/20 px-1.5 py-px font-mono text-[11px] uppercase tracking-wider text-sky-300">
      yours
    </span>
  )
}

export function Chapter({ chapter, mine = false }: { chapter: ManualChapter; mine?: boolean }) {
  return (
    <section id={chapter.id} className="scroll-mt-6 space-y-6 break-inside-avoid-page">
      <header className="border-t-2 border-slate-200 pt-4 print:border-black">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-slate-400">{chapter.number}</span>
          {mine && <YoursTag />}
        </div>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-100 print:text-black">
          {chapter.title}
        </h2>
        <p className="mt-1 text-sm text-slate-400 print:text-slate-700">{chapter.summary}</p>
      </header>
      {chapter.sections.map((s) => (
        <section key={s.id} id={s.id} className="scroll-mt-6 space-y-3">
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.10em] text-slate-400 print:text-slate-700">
            {s.title}
          </h3>
          {s.body}
        </section>
      ))}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Records (admin, Quality, Project Management)
// ---------------------------------------------------------------------------

function Records({ data }: { data: TrainingStatus }) {
  const [role, setRole] = useState('')
  const [history, setHistory] = useState(false)
  const roster = useQuery({
    queryKey: ['training-roster', role, history],
    queryFn: () =>
      trainingApi.roster({ role: role || undefined, include_superseded: history }),
  })
  const people = useQuery({ queryKey: ['training-people'], queryFn: trainingApi.people })

  const notStarted = useMemo(() => {
    if (!roster.data || !people.data) return []
    const have = new Set(
      roster.data.items
        .filter((i) => i.version === i.required_version)
        .map((i) => `${i.user_id}:${i.role}`),
    )
    return people.data.flatMap((p) =>
      p.roles
        .filter((r) => !role || r === role)
        .filter((r) => !have.has(`${p.user_id}:${r}`))
        .map((r) => ({ ...p, role: r })),
    )
  }, [roster.data, people.data, role])

  const labelOf = (r: string) => data.catalog.find((c) => c.role === r)?.label ?? r

  return (
    <div className="space-y-8">
      <p className="text-[13px] text-slate-400" data-testid="records-scoring-note">
        As in TWOS, the practical tasks are checked in the trainee's browser against a training
        copy that never reaches the server; the record keeps the result the browser reports,
        with who trained the person and when.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="Signed off" value={roster.data?.active ?? '-'} />
        <Tile label="Tasks open" value={roster.data?.pending ?? '-'} />
        <Tile label="Not started" value={people.data ? notStarted.length : '-'} />
      </div>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-200">Roster</h2>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <select
              aria-label="Role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded-lg border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-slate-200"
            >
              <option value="">All roles</option>
              {data.catalog.map((c) => (
                <option key={c.role} value={c.role}>
                  {c.label}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-slate-400">
              <input
                type="checkbox"
                checked={history}
                onChange={(e) => setHistory(e.target.checked)}
              />
              Include superseded
            </label>
            <a href={rosterCsvUrl(true)} className={BUTTON_SECONDARY}>
              Export CSV
            </a>
          </div>
        </div>
        <div className="overflow-x-auto rounded-lg border border-slate-700">
          <table className="w-full text-sm">
            <thead className="bg-slate-800 text-left text-[11px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">Person</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Version</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Trained on</th>
                <th className="px-3 py-2">Trainer</th>
                <th className="px-3 py-2">Tasks passed</th>
                <th className="px-3 py-2">Software</th>
                <th className="px-3 py-2 text-right">Attempts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {(roster.data?.items ?? []).map((i) => (
                <tr key={i.signoff_id} className={i.status === 'superseded' ? 'opacity-50' : ''}>
                  <td className="px-3 py-2">
                    <div className="text-slate-200">{i.display_name ?? i.email}</div>
                    <div className="text-[11px] text-slate-400">{i.email}</div>
                  </td>
                  <td className="px-3 py-2 text-slate-300">{i.label}</td>
                  <td className="px-3 py-2 text-slate-400">
                    {i.version}
                    {i.version < i.required_version && ` of ${i.required_version}`}
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-[12px] text-slate-300">
                      {i.status === 'active'
                        ? 'Signed off'
                        : i.status === 'pending_tasks'
                          ? i.carried_from_id
                            ? 'Re-training due'
                            : 'Tasks open'
                          : 'Superseded'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-400">{formatDate(i.training_date)}</td>
                  <td className="px-3 py-2 text-slate-400">
                    {i.trainer_name ?? '-'}
                    {i.trainer_source === 'roster' && (
                      <span className="ml-1 text-[11px] text-slate-400">(roster)</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-400">{formatDateTime(i.tasks_passed_at)}</td>
                  <td className="px-3 py-2 font-mono text-[12px] text-slate-400">
                    {i.software_version ?? '-'}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-400">
                    {i.attempts}
                    {i.failed_attempts > 0 && (
                      <span className="text-amber-400/80"> ({i.failed_attempts} failed)</span>
                    )}
                  </td>
                </tr>
              ))}
              {roster.data && roster.data.items.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-slate-400">
                    No training recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {notStarted.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-slate-400">
              Not started: {notStarted.length}
            </summary>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
              {notStarted.map((p) => (
                <li key={`${p.user_id}:${p.role}`} className="text-slate-400">
                  {p.name} <span className="text-slate-400">· {labelOf(p.role)}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <RecordAttendance data={data} people={people.data ?? []} />
        <PublishVersion data={data} />
      </div>
      <GateSwitch data={data} />
    </div>
  )
}

function Tile({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-3xl font-bold text-slate-100">{value}</div>
    </div>
  )
}

function RecordAttendance({
  data,
  people,
}: {
  data: TrainingStatus
  people: { user_id: number; name: string; email: string; roles: string[] }[]
}) {
  const qc = useQueryClient()
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState('')
  const [date, setDate] = useState('')
  const [trainer, setTrainer] = useState('')
  const person = people.find((p) => String(p.user_id) === userId)
  const save = useMutation({
    mutationFn: () =>
      trainingApi.recordRoster({
        user_id: Number(userId),
        role,
        training_date: date,
        trainer_name: trainer.trim(),
      }),
    onSuccess: () => {
      toast.success('Attendance recorded. The practical tasks are still owed.')
      setUserId('')
      setRole('')
      qc.invalidateQueries({ queryKey: ['training-roster'] })
    },
    onError: (e) => toastError(e, 'Could not record the attendance'),
  })
  const ready = userId && role && date && trainer.trim().length > 1
  return (
    <section className="space-y-3 rounded-lg border border-slate-700 bg-slate-800/60 p-5">
      <h2 className="text-sm font-semibold text-slate-200">Record attendance</h2>
      <p className="text-[13px] text-slate-400">
        For a session you witnessed. The person still takes the practical check themselves.
      </p>
      <select
        aria-label="Person"
        value={userId}
        onChange={(e) => {
          setUserId(e.target.value)
          const p = people.find((x) => String(x.user_id) === e.target.value)
          if (p && p.roles.length === 1) setRole(p.roles[0])
        }}
        className={INPUT}
      >
        <option value="">Person</option>
        {/* Four eyes: your own attendance is recorded by somebody else. */}
        {people.filter((p) => p.user_id !== data.user_id).map((p) => (
          <option key={p.user_id} value={p.user_id}>
            {p.name} ({p.email})
          </option>
        ))}
      </select>
      <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} className={INPUT}>
        <option value="">Role</option>
        {data.catalog
          .filter((c) => !person || person.roles.includes(c.role))
          .map((c) => (
            <option key={c.role} value={c.role}>
              {c.label}
            </option>
          ))}
      </select>
      <div className="grid gap-3 sm:grid-cols-2">
        <DateInput
          aria-label="Training date"
          max={todayIso()}
          value={date}
          onChange={setDate}
          commitOnChange
          className={INPUT}
        />
        <input
          aria-label="Trainer"
          placeholder="Trainer"
          value={trainer}
          onChange={(e) => setTrainer(e.target.value)}
          className={INPUT}
        />
      </div>
      <button
        type="button"
        disabled={!ready || save.isPending}
        onClick={() => save.mutate()}
        className={BUTTON_PRIMARY}
      >
        Record attendance
      </button>
    </section>
  )
}

function PublishVersion({ data }: { data: TrainingStatus }) {
  const qc = useQueryClient()
  const [role, setRole] = useState('')
  const [summary, setSummary] = useState('')
  const versions = useQuery({ queryKey: ['training-versions'], queryFn: trainingApi.versions })
  const current = data.catalog.find((c) => c.role === role)
  const publish = useMutation({
    mutationFn: () => trainingApi.publish(role, summary.trim()),
    onSuccess: (v) => {
      toast.success(`${current?.label ?? v.role}: version ${v.version} published`)
      setSummary('')
      qc.invalidateQueries({ queryKey: ['training-versions'] })
      qc.invalidateQueries({ queryKey: ['training-roster'] })
      qc.invalidateQueries({ queryKey: ['training-status'] })
    },
    onError: (e) => toastError(e, 'Could not publish the version'),
  })
  return (
    <section className="space-y-3 rounded-lg border border-slate-700 bg-slate-800/60 p-5">
      <h2 className="text-sm font-semibold text-slate-200">Publish a new version</h2>
      <p className="text-[13px] text-slate-400">
        Asks everybody signed off in this role to take the practical check again. Their
        confirmation carries over. Nothing is blocked.
      </p>
      <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} className={INPUT}>
        <option value="">Role</option>
        {data.catalog.map((c) => (
          <option key={c.role} value={c.role}>
            {c.label} (now version {c.required_version})
          </option>
        ))}
      </select>
      <textarea
        aria-label="What changed"
        rows={3}
        placeholder="What changed, in one or two sentences. Everybody re-training reads this."
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
        className={INPUT}
      />
      <button
        type="button"
        disabled={!role || !summary.trim() || publish.isPending}
        onClick={() => publish.mutate()}
        className={BUTTON_PRIMARY}
      >
        Publish version {current ? current.required_version + 1 : ''}
      </button>
      {(versions.data ?? []).length > 0 && (
        <ul className="space-y-1 border-t border-slate-700/70 pt-3 text-[13px]">
          {versions.data!.map((v) => (
            <li key={v.id} className="text-slate-400">
              <span className="text-slate-200">
                {data.catalog.find((c) => c.role === v.role)?.label ?? v.role} v{v.version}
              </span>{' '}
              · {formatDate(v.published_at)} · {v.published_by}
              {v.software_version && ` · ${v.software_version}`}
              <div className="text-slate-400">{v.summary}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function GateSwitch({ data }: { data: TrainingStatus }) {
  const { isAdmin } = useAuth()
  const qc = useQueryClient()
  const [confirmOn, setConfirmOn] = useState(false)
  const flip = useMutation({
    mutationFn: (on: boolean) => trainingApi.setGate(on),
    onSuccess: (_d, on) => {
      toast.success(on ? 'Training gate switched on' : 'Training gate switched off')
      return qc.invalidateQueries({ queryKey: ['training-status'] })
    },
  })
  return (
    <section className="space-y-2 rounded-lg border border-slate-700 bg-slate-800/40 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Training gate</h2>
          <p className="mt-0.5 text-[13px] text-slate-400">
            {data.gate_enabled
              ? 'On: change actions are held for anybody whose owed training is not signed off.'
              : 'Off: training is recorded, nothing is blocked.'}
            {data.gate_source === 'env' && ' Set by the installation (TRAINING_GATE).'}
          </p>
        </div>
        {isAdmin && data.gate_source !== 'env' && (
          <button
            type="button"
            disabled={flip.isPending}
            onClick={() => {
              if (data.gate_enabled) {
                flip.mutate(false, { onError: (e) => toastError(e, 'Could not switch the gate off') })
              } else {
                setConfirmOn(true)
              }
            }}
            className={BUTTON_SECONDARY}
          >
            {data.gate_enabled ? 'Switch off' : 'Switch on'}
          </button>
        )}
      </div>
      <ConfirmDialog
        open={confirmOn}
        title="Switch the training gate on?"
        body="Change actions will be refused to everybody whose owed training is not signed off."
        confirmLabel="Switch the gate on"
        errorFallback="Could not switch the gate on"
        onConfirm={() => flip.mutateAsync(true)}
        onClose={() => setConfirmOn(false)}
      />
    </section>
  )
}
