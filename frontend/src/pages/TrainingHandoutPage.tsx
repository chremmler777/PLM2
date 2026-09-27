import { useQuery } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { trainingApi } from '../api/training'
import { formatDate, formatDateTime, todayIso } from '../lib/format'
import { chaptersFor } from '../training/manual/chapters'
import { handoutFor, practiceOf, type HandoutBlock } from '../training/manual/content/handouts'
import { TASKS } from '../training/tasks'
import { ComingTasks } from '../training/ui'
import { Chapter } from './TrainingPage'

//: The printable handout for one role. First the one-page handout (the same
//: content as docs/training/handouts/<role>.md, from content/handouts.ts),
//: then the practical check (what this build runs, and what comes later) and
//: a record block the trainer and the trainee fill in by hand at the session.
//: "With the full chapters" appends the role's manual chapters for a longer
//: print. White page and black text on paper, the screen chrome hidden.

export default function TrainingHandoutPage() {
  const { role = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const full = params.get('full') === '1'
  const status = useQuery({ queryKey: ['training-status'], queryFn: trainingApi.status })
  const catalog = status.data?.catalog.find((c) => c.role === role)
  const mine = status.data?.roles.find((r) => r.role === role)

  if (status.isLoading) return null
  if (!catalog) {
    return (
      <div className="p-8 text-slate-300">
        Unknown training role. <Link to="/training" className="underline">Back to Training</Link>
      </div>
    )
  }
  const handout = handoutFor(role)
  const chapters = chaptersFor([role])
  const inCheck = new Set(catalog.tasks)
  const coming = practiceOf(role).coming.filter((t) => !inCheck.has(t.key))

  return (
    <div className="min-h-screen bg-slate-900 print:bg-white">
      <style>{'@page { margin: 14mm 14mm; }'}</style>
      <div className="sticky top-0 z-10 border-b border-slate-700 bg-slate-800/95 print:hidden">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-6 py-3 text-sm">
          <Link to="/training?tab=manual" className="text-slate-300 hover:text-white">
            Back to Training
          </Link>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-slate-300">
              <input
                type="checkbox"
                checked={full}
                onChange={(e) => setParams(e.target.checked ? { full: '1' } : {}, { replace: true })}
                className="h-4 w-4 accent-sky-500"
              />
              With the full chapters
            </label>
            <button
              type="button"
              onClick={() => window.print()}
              className="rounded-lg bg-sky-600 px-4 py-1.5 font-semibold text-white hover:bg-sky-500"
            >
              Print
            </button>
          </div>
        </div>
      </div>

      <article className="mx-auto max-w-3xl space-y-8 px-6 py-8 print:max-w-none print:space-y-5 print:px-0 print:py-0">
        <header className="space-y-2">
          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400 print:text-slate-500">
            ECR training handout · {status.data?.software_version}
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-100 print:text-2xl print:text-black">
            {catalog.label}
          </h1>
          <p className="text-sm text-slate-400 print:text-slate-700">
            For {catalog.departments.join(', ')}. Material version {catalog.required_version},
            printed {formatDate(todayIso())}.
            {handout && <> The full chapter is in the manual, chapter {handout.chapter}.</>}
          </p>
        </header>

        {handout && (
          <section data-testid="one-page-handout" className="space-y-5 print:space-y-3">
            <p className="text-[15px] leading-relaxed text-slate-200 print:text-[13px] print:text-black">
              <span className="font-semibold">Your job:</span> {handout.job}
            </p>
            {handout.blocks.map((b) => (
              <HandoutSection key={b.h2} block={b} />
            ))}
          </section>
        )}

        <section className="break-inside-avoid space-y-3 rounded-lg border border-slate-700 p-5 print:border-slate-400 print:p-4">
          <h2 className="text-sm font-semibold text-slate-100 print:text-black">
            Your practical check
          </h2>
          <p className="text-sm text-slate-400 print:text-slate-700">
            Taken on the Training page after the session, on the real screens in a training
            copy. Nothing done there reaches the live system. Training is recorded, not
            blocking.
          </p>
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-slate-300 print:text-black">
            {catalog.tasks.map((k) => (
              <li key={k}>
                <span className="font-medium">{TASKS[k]?.title ?? k}.</span>{' '}
                <span className="text-slate-400 print:text-slate-700">{TASKS[k]?.why}</span>
              </li>
            ))}
          </ol>
          <ComingTasks tasks={coming} />
        </section>

        <section className="break-inside-avoid space-y-4 rounded-lg border border-slate-700 p-5 print:border-slate-400 print:p-4">
          <h2 className="text-sm font-semibold text-slate-100 print:text-black">
            Training record
          </h2>
          {mine?.attested_at ? (
            <dl className="grid grid-cols-2 gap-3 text-sm text-slate-300 print:text-black">
              <div>Trained on: {formatDate(mine.training_date)}</div>
              <div>Trainer: {mine.trainer_name}</div>
              <div>Tasks passed: {formatDateTime(mine.tasks_passed_at)}</div>
              <div>Software version: {mine.software_version ?? '-'}</div>
            </dl>
          ) : (
            <div className="grid gap-6 text-sm text-slate-400 print:gap-4 print:text-slate-700 sm:grid-cols-2 print:grid-cols-3">
              {['Name', 'Department', 'Trainer', 'Date of the session', 'Signature', 'Trainer signature'].map(
                (label) => (
                  <div key={label} className="border-b border-slate-600 pb-6 print:border-slate-400 print:pb-4">
                    {label}
                  </div>
                ),
              )}
            </div>
          )}
          <p className="text-[12px] text-slate-400 print:text-slate-500">
            The record that counts is the one on the Training page. This sheet is for the
            session.
          </p>
        </section>

        {(full || !handout) && (
          <div className="space-y-10 print:break-before-page">
            {chapters.map((c) => (
              <Chapter key={c.id} chapter={c} />
            ))}
          </div>
        )}
      </article>
    </div>
  )
}

function HandoutSection({ block }: { block: HandoutBlock }) {
  return (
    <section className="break-inside-avoid space-y-2">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.10em] text-slate-400 print:text-slate-700">
        {block.h2}
      </h2>
      {'table' in block ? (
        <table className="w-full text-left text-sm print:text-[12px] print:text-black">
          <thead>
            <tr className="border-b border-slate-700 print:border-slate-400">
              {block.table.head.map((h) => (
                <th key={h} scope="col" className="py-1.5 pr-3 font-medium text-slate-100 print:py-1 print:text-black">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.table.rows.map((r) => (
              <tr key={r[0]} className="border-b border-slate-800 align-top print:border-slate-200">
                {r.map((cell, i) => (
                  <td
                    key={i}
                    className={`py-1.5 pr-3 print:py-1 ${
                      i === 0 ? 'font-medium text-slate-200' : 'text-slate-300'
                    } print:text-black`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : 'points' in block ? (
        <ul className="space-y-1.5">
          {block.points.map(([lead, rest]) => (
            <li key={lead} className="flex gap-2.5 text-sm leading-relaxed print:text-[12px]">
              <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-slate-500" aria-hidden />
              <span className="text-slate-300 print:text-black">
                <span className="font-medium text-slate-100 print:text-black">{lead}</span>
                {rest ? <> {rest}</> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm leading-relaxed text-slate-300 print:text-[12px] print:text-black">{block.p}</p>
      )}
    </section>
  )
}
