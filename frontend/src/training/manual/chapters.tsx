import type { ReactNode } from 'react'
import { Callout, P, Pending, Points, Steps } from './kit'

//: The ECR manual: per-role chapters, versioned with the app so a screen and
//: its description cannot drift apart (same rule as TWOS content.tsx).
//:
//: Format, for when the content is written (after the UI polish):
//:   - A chapter is one entry in CHAPTERS. `roles` lists the training role
//:     keys it belongs to (backend app/services/training.py CURRICULA);
//:     leave it out for a chapter everybody reads.
//:   - A section is { id, title, body }. The id is its anchor, unique across
//:     the manual, prefixed with the chapter id.
//:   - A body is composed from kit.tsx (Lede, P, H3, Points, Steps, Callout,
//:     Figure). Screenshots go in frontend/public/manual/ and are referenced
//:     by file name: <Figure src="sales-start.png" alt="..." />.
//:   - Until a section is written its body is <Pending />.
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

/** A section whose content is still to be written. */
const stub = (id: string, title: string): ManualSection => ({ id, title, body: <Pending /> })

export const CHAPTERS: ManualChapter[] = [
  // ------------------------------------------------------------------ 01
  {
    id: 'basics',
    number: '01',
    title: 'Why the ECR process, and who owns what',
    summary: 'One place for every engineering change. The same information for everyone.',
    sections: [
      stub('basics-why', 'What the change process is for'),
      stub('basics-owners', 'Who owns which step'),
      stub('basics-finding', 'Finding your work: My Tasks and the change page'),
    ],
  },
  // ------------------------------------------------------------------ 02
  {
    id: 'flow',
    number: '02',
    title: 'A change, end to end',
    summary: 'From the customer\'s request to the released part.',
    sections: [
      stub('flow-capture', 'Capture'),
      stub('flow-scoping', 'Scoping'),
      stub('flow-assessment', 'Assessment'),
      stub('flow-costing', 'Costing and the quote'),
      stub('flow-implementation', 'Approval and implementation'),
      stub('flow-validation', 'Validation and release'),
    ],
  },
  // ------------------------------------------------------------------ 03
  {
    id: 'pm',
    number: '03',
    title: 'Project Management',
    summary: 'Leading a change: priority, deadlines, scoping, the plan.',
    roles: ['project_management'],
    sections: [
      stub('pm-takeover', 'Taking over a captured change'),
      stub('pm-priority', 'Priority and the deadlines'),
      stub('pm-scoping', 'The scoping meeting'),
      stub('pm-plan', 'Timing and the plan'),
    ],
  },
  // ------------------------------------------------------------------ 04
  {
    id: 'sales',
    number: '04',
    title: 'Sales',
    summary: 'Starting a change request, the quote, the customer\'s answer.',
    roles: ['sales'],
    sections: [
      stub('sales-start', 'Starting a change request'),
      stub('sales-documents', 'The customer\'s documents'),
      stub('sales-quote', 'The quote and the customer\'s answer'),
    ],
  },
  // ------------------------------------------------------------------ 05
  {
    id: 'engineering',
    number: '05',
    title: 'Engineers',
    summary:
      'Development, Tool Engineer, Manufacturing Engineer, Process Engineer, APQP, ' +
      'Packaging Engineer: assessing, costing and implementing a change.',
    roles: ['engineering'],
    sections: [
      stub('eng-assessment', 'Your assessment'),
      stub('eng-checklist', 'The checklist, row by row'),
      stub('eng-risks', 'Flagging a risk on a row'),
      stub('eng-costing', 'Your costing input'),
      stub('eng-implementation', 'Implementation and validation'),
    ],
  },
  // ------------------------------------------------------------------ 06
  {
    id: 'scheduling',
    number: '06',
    title: 'Scheduling',
    summary: 'Capacity, bank build or running change, the plan.',
    roles: ['scheduling'],
    sections: [
      stub('sch-assessment', 'Your assessment'),
      stub('sch-bankbuild', 'Bank build or running change'),
      stub('sch-plan', 'The plan'),
    ],
  },
  // ------------------------------------------------------------------ 07
  {
    id: 'quality',
    number: '07',
    title: 'Quality',
    summary: 'Risks, validation issues, release.',
    roles: ['quality'],
    sections: [
      stub('qa-assessment', 'Your assessment'),
      stub('qa-validation', 'Validation issues'),
      stub('qa-release', 'Release'),
    ],
  },
  // ------------------------------------------------------------------ 08
  {
    id: 'finance',
    number: '08',
    title: 'Finance',
    summary: 'Rates, the cost sheet, the P&L of a change.',
    roles: ['finance'],
    sections: [
      stub('fin-assessment', 'Your assessment'),
      stub('fin-costsheet', 'The cost sheet and its rates'),
      stub('fin-pnl', 'The P&L of a change'),
    ],
  },
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
