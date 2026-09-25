import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { trainingApi } from '../api/training'
import { formatDate, formatDateTime, todayIso } from '../lib/format'
import { chaptersFor } from '../training/manual/chapters'
import { TASKS } from '../training/tasks'
import { Chapter } from './TrainingPage'

//: The printable handout for one role: the chapters that role reads, the
//: practical tasks it will be asked to do, and a record block the trainer and
//: the trainee fill in by hand at the session. Same content as the in-app
//: manual (one source), laid out for paper: white page, black text, the
//: screen chrome hidden when printing.

export default function TrainingHandoutPage() {
  const { role = '' } = useParams()
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
  const chapters = chaptersFor([role])

  return (
    <div className="min-h-screen bg-slate-900 print:bg-white">
      <style>{'@page { margin: 16mm 14mm; }'}</style>
      <div className="sticky top-0 z-10 border-b border-slate-700 bg-slate-800/95 print:hidden">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-3 text-sm">
          <Link to="/training?tab=manual" className="text-slate-300 hover:text-white">
            Back to Training
          </Link>
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-lg bg-sky-600 px-4 py-1.5 font-semibold text-white hover:bg-sky-500"
          >
            Print
          </button>
        </div>
      </div>

      <article className="mx-auto max-w-3xl space-y-10 px-6 py-8 print:max-w-none print:px-0 print:py-0">
        <header className="space-y-2">
          <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500 print:text-slate-600">
            ECR training handout · {status.data?.software_version}
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-100 print:text-black">
            {catalog.label}
          </h1>
          <p className="text-sm text-slate-400 print:text-slate-700">
            For {catalog.departments.join(', ')}. Material version {catalog.required_version},
            printed {formatDate(todayIso())}.
          </p>
        </header>

        <section className="space-y-3 rounded-lg border border-slate-700 p-5 print:border-slate-400">
          <h2 className="text-sm font-semibold text-slate-100 print:text-black">
            The practical check
          </h2>
          <p className="text-sm text-slate-400 print:text-slate-700">
            Taken on the Training page after the session, on the real screens in a training
            copy. Nothing done there reaches the live system.
          </p>
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-slate-300 print:text-black">
            {catalog.tasks.map((k) => (
              <li key={k}>
                <span className="font-medium">{TASKS[k]?.title ?? k}.</span>{' '}
                <span className="text-slate-400 print:text-slate-700">{TASKS[k]?.why}</span>
              </li>
            ))}
          </ol>
        </section>

        {chapters.map((c) => (
          <Chapter key={c.id} chapter={c} />
        ))}

        <section className="break-inside-avoid space-y-4 rounded-lg border border-slate-700 p-5 print:border-slate-400">
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
            <div className="grid gap-6 text-sm text-slate-400 print:text-slate-700 sm:grid-cols-2">
              {['Name', 'Department', 'Trainer', 'Date of the session', 'Signature', 'Trainer signature'].map(
                (label) => (
                  <div key={label} className="border-b border-slate-600 pb-6 print:border-slate-400">
                    {label}
                  </div>
                ),
              )}
            </div>
          )}
          <p className="text-[12px] text-slate-500 print:text-slate-600">
            The record that counts is the one on the Training page. This sheet is for the
            session.
          </p>
        </section>
      </article>
    </div>
  )
}
