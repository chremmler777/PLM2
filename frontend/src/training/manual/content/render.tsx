import type { ReactNode } from 'react'
import { ImageIcon } from 'lucide-react'
import { Callout, Figure, H3, Lede, P, Points, Steps } from '../kit'
import type { Block, ContentSection, ShotSlot } from './types'

//: Renders the content blocks onto the manual kit. ../chapters.tsx builds
//: chapters 01 to 08 with it (WIRING.md, section 1).
//:
//: A screenshot slot renders as a named "Screenshot follows" frame until its
//: file is in frontend/public/manual/ and its stem is listed in `available`.
//: The frame says what the picture will show, so the text around it still
//: reads, on screen and on paper.

export function renderBlocks(blocks: Block[], available: ReadonlySet<string> = new Set()): ReactNode {
  return (
    <div className="space-y-4">
      {blocks.map((b, i) => (
        <BlockView key={i} block={b} available={available} />
      ))}
    </div>
  )
}

export function renderSection(s: ContentSection, available?: ReadonlySet<string>): ReactNode {
  return renderBlocks(s.blocks, available)
}

function BlockView({ block, available }: { block: Block; available: ReadonlySet<string> }) {
  if ('lede' in block) return <Lede>{block.lede}</Lede>
  if ('p' in block) return <P>{block.p}</P>
  if ('h3' in block) return <H3>{block.h3}</H3>
  if ('points' in block) return <Points items={block.points} />
  if ('steps' in block) return <Steps items={block.steps} />
  if ('callout' in block) {
    return (
      <Callout tone={block.tone} title={block.title}>
        {block.callout}
      </Callout>
    )
  }
  if ('table' in block) {
    return (
      <table className="w-full text-left text-sm print:text-black">
        <thead>
          <tr className="border-b border-slate-700 print:border-slate-300">
            {block.table.head.map((h) => (
              <th key={h} className="py-1.5 pr-4 font-medium text-slate-100 print:text-black">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.table.rows.map(([a, b]) => (
            <tr key={a} className="border-b border-slate-800 align-top print:border-slate-200">
              <td className="py-1.5 pr-4 font-medium text-slate-200 print:text-black">{a}</td>
              <td className="py-1.5 text-slate-300 print:text-black">{b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }
  if (available.has(block.shot)) {
    return <Figure src={`${block.shot}.png`} alt={block.alt} caption={block.caption} />
  }
  return <ShotPlaceholder slot={block} />
}

/** The frame a screenshot slot shows until its picture exists. */
export function ShotPlaceholder({ slot }: { slot: ShotSlot }) {
  return (
    <figure
      data-shot={slot.shot}
      data-testid={`shot-${slot.shot}`}
      className="break-inside-avoid rounded-lg border border-dashed border-slate-600 bg-slate-800/40 px-4 py-3.5 print:border-slate-400 print:bg-white"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <ImageIcon aria-hidden="true" size={14} className="shrink-0 text-slate-400 print:text-slate-600" />
        <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-400 print:text-slate-600">
          Screenshot follows
        </span>
        <code className="ml-auto font-mono text-[11px] text-slate-500 print:text-slate-600">{slot.shot}</code>
      </div>
      <figcaption className="mt-1.5 text-[13px] leading-relaxed text-slate-300 print:text-black">
        {slot.alt}
        {slot.caption ? <span className="mt-1 block text-[11px] text-slate-400">{slot.caption}</span> : null}
      </figcaption>
    </figure>
  )
}
