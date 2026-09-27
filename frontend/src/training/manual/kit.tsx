import type { ReactNode } from 'react'

//: Presentational building blocks for the ECR manual, ported from TWOS
//: (components/manual/kit.tsx there) onto PLM2's slate palette. Deliberately
//: dumb: no data fetching, no role logic. chapters.tsx composes these, the
//: Training page and the printable handout frame them.
//:
//: Every block also prints: the handout renders the same chapters on white.

export function Lede({ children }: { children: ReactNode }) {
  return (
    <p className="text-[15px] leading-relaxed text-slate-200 print:text-black">{children}</p>
  )
}

export function P({ children }: { children: ReactNode }) {
  return (
    <p className="text-sm leading-relaxed text-slate-300 print:text-black">{children}</p>
  )
}

export function H3({ children }: { children: ReactNode }) {
  return (
    <h4 className="text-sm font-semibold tracking-tight text-slate-100 print:text-black">
      {children}
    </h4>
  )
}

/** A bulleted list where each item leads with a bold phrase. */
export function Points({ items }: { items: [string, ReactNode][] }) {
  return (
    <ul className="space-y-2">
      {items.map(([lead, rest], i) => (
        <li key={i} className="flex gap-2.5 text-sm leading-relaxed">
          <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-slate-500" />
          <span className="text-slate-300 print:text-black">
            <span className="font-medium text-slate-100 print:text-black">{lead}</span>
            {rest ? <> {rest}</> : null}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function Steps({ items }: { items: { title: string; body: ReactNode }[] }) {
  return (
    <ol className="space-y-2.5">
      {items.map((s, i) => (
        <li
          key={i}
          className="flex gap-3 rounded-lg border border-slate-700/70 px-3.5 py-3 print:border-slate-300"
        >
          <span className="mt-px w-4 shrink-0 font-mono text-[11px] font-semibold text-slate-400">
            {i + 1}
          </span>
          <div className="min-w-0 space-y-1">
            <div className="text-sm font-medium text-slate-100 print:text-black">{s.title}</div>
            <div className="text-sm leading-relaxed text-slate-400 print:text-slate-700">{s.body}</div>
          </div>
        </li>
      ))}
    </ol>
  )
}

const CALLOUT_TONES = {
  note: 'border-slate-700 bg-slate-800/60',
  warn: 'border-amber-500/40 bg-amber-500/10',
  rule: 'border-red-500/30 bg-red-500/10',
} as const

export function Callout({
  tone = 'note',
  title,
  children,
}: {
  tone?: keyof typeof CALLOUT_TONES
  title?: string
  children: ReactNode
}) {
  return (
    <div
      className={`rounded-lg border px-4 py-3.5 space-y-1.5 print:border-slate-400 print:bg-white ${CALLOUT_TONES[tone]}`}
    >
      {title && (
        <div className="text-sm font-semibold tracking-tight text-slate-100 print:text-black">
          {title}
        </div>
      )}
      <div className="text-[13px] leading-relaxed text-slate-300 print:text-black">{children}</div>
    </div>
  )
}

/**
 * A screenshot from frontend/public/manual/. Framed so it reads as an embedded
 * picture on the dark page and on paper.
 */
export function Figure({ src, alt, caption }: { src: string; alt: string; caption?: string }) {
  return (
    <figure className="space-y-1.5 break-inside-avoid">
      <img
        src={`${import.meta.env.BASE_URL}manual/${src}`}
        alt={alt}
        loading="lazy"
        className="w-full rounded-lg border border-slate-700 print:border-slate-300"
      />
      {caption && <figcaption className="text-[11px] text-slate-400">{caption}</figcaption>}
    </figure>
  )
}

/**
 * The placeholder for a section whose content is written once its screens are
 * final. Neutral on purpose: it is read by trainees until then.
 */
export function Pending() {
  return (
    <p
      data-testid="manual-pending"
      className="rounded-lg border border-dashed border-slate-700 px-3.5 py-2.5 text-[13px] text-slate-400 print:border-slate-300"
    >
      Content follows with the final screens.
    </p>
  )
}
