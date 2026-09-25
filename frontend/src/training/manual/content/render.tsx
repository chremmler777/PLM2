import type { ReactNode } from 'react'
import { Callout, Figure, H3, Lede, P, Points, Steps } from '../kit'
import type { Block, ContentSection } from './types'

//: Renders the content blocks onto the manual kit. Not used by the app yet:
//: WIRING.md describes the one-line swap in ../chapters.tsx.
//:
//: A screenshot slot renders as a labelled placeholder until its file is in
//: frontend/public/manual/ and its stem is listed in `available`. That keeps
//: an unfinished picture visible to the writer and neutral to a trainee.

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
  return (
    <p
      data-shot={block.shot}
      className="rounded-lg border border-dashed border-slate-700 px-3.5 py-2.5 text-[13px] text-slate-500 print:border-slate-300"
    >
      Screenshot follows with the final screens.
    </p>
  )
}
