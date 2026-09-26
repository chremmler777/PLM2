import type { ReactNode } from 'react'
import { contentFor } from './content'
import { renderBlocks } from './content/render'
import { Callout, P, Points, Steps } from './kit'

//: The ECR manual: per-role chapters, versioned with the app so a screen and
//: its description cannot drift apart (same rule as TWOS content.tsx).
//:
//: Chapters 01 to 08 are written as data in ./content (one file per role,
//: see content/WIRING.md) and rendered onto the kit by content/render.tsx.
//: Chapter 09 (the training record) is written here.
//:
//: Format:
//:   - A chapter is one entry in CHAPTERS. `roles` lists the training role
//:     keys it belongs to (backend app/services/training.py CURRICULA);
//:     leave it out for a chapter everybody reads.
//:   - A section is { id, title, body }. The id is its anchor, unique across
//:     the manual, prefixed with the chapter id.
//:   - Screenshots go in frontend/public/manual/<slot>.png; add the slot name
//:     to SHOTS_AVAILABLE and its placeholder becomes the picture.
//:   - No em-dashes in the copy.
//:   - When a chapter changes what a role has to know, bump code_version for
//:     that role in the backend curriculum, and publish the new version from
//:     Training, Records when the plant is ready for it.

export type ManualSection = { id: string; title: string; body: ReactNode }

export type ManualChapter = {
  id: string
  number: string
  title: string
  summary: string
  /** Training role keys whose chapter this is. Undefined means everyone. */
  roles?: string[]
  sections: ManualSection[]
}

/**
 * Screenshot slots that have a file in public/manual/ (the stem, no ".png").
 * Grows as the screenshots land; every other slot renders as a named
 * "Screenshot follows" frame. The slot list is in content/WIRING.md.
 */
export const SHOTS_AVAILABLE: ReadonlySet<string> = new Set<string>([])

/** Chapter 01 to 08 from the written content, by the chapter id. */
function written(id: string, number: string, roles?: string[]): ManualChapter {
  const c = contentFor(id)
  if (!c) throw new Error(`No written content for manual chapter ${id}`)
  return {
    id,
    number,
    title: c.title,
    summary: c.summary,
    ...(roles ? { roles } : {}),
    sections: c.sections.map((s) => ({
      id: s.id,
      title: s.title,
      body: renderBlocks(s.blocks, SHOTS_AVAILABLE),
    })),
  }
}

export const CHAPTERS: ManualChapter[] = [
  written('basics', '01'),
  written('flow', '02'),
  written('pm', '03', ['project_management']),
  written('sales', '04', ['sales']),
  written('engineering', '05', ['engineering']),
  written('scheduling', '06', ['scheduling']),
  written('quality', '07', ['quality']),
  written('finance', '08', ['finance']),
  // ------------------------------------------------------------------ 09
  {
    id: 'record',
    number: '09',
    title: 'Your training record',
    summary: 'How training is recorded, and when it is due again.',
    sections: [
      {
        id: 'record-how',
        title: 'How it works',
        body: (
          <>
            <Steps
              items={[
                {
                  title: 'Your session',
                  body: 'Held in person, by your lead or a trained colleague.',
                },
                {
                  title: 'Confirm it',
                  body:
                    'On the Training page, name who trained you and the day the session ' +
                    'was held. If it has not taken place yet, do not confirm: ask for it.',
                },
                {
                  title: 'The practical check',
                  body:
                    'A few short tasks on the real screens, in a training copy. Nothing ' +
                    'you do there reaches the live system. Retry as often as you like.',
                },
                {
                  title: 'Signed off',
                  body:
                    'Your record shows the date, your trainer, when you passed and the ' +
                    'software version you were trained on.',
                },
              ]}
            />
          </>
        ),
      },
      {
        id: 'record-retrain',
        title: 'When re-training is due',
        body: (
          <>
            <P>
              When a change to the software changes what your role has to know, a new
              version of the material is published. Your record then shows re-training as
              due. Your confirmation carries over; only the practical check is taken again.
            </P>
            <Points
              items={[
                ['Where to see it:', 'the Training page, under My training.'],
                ['What it asks:', 'the tasks of the new version, nothing else.'],
              ]}
            />
            <Callout title="Recorded, not blocking">
              Training is recorded for the audit. It does not stop you from working on a
              change.
            </Callout>
          </>
        ),
      },
    ],
  },
]

/** The chapters a reader holding these roles is shown first. */
export function chaptersFor(roles: string[]): ManualChapter[] {
  return CHAPTERS.filter((c) => !c.roles || c.roles.some((r) => roles.includes(r)))
}
