import type { ContentChapter, PracticeTaskSpec } from './types'

//: Chapter 07, Quality. qa-assessment, qa-validation and qa-release replace
//: the stubs of the same id in ../chapters.tsx.

export const qualityChapter: ContentChapter = {
  id: 'quality',
  number: '07',
  title: 'Quality',
  summary: 'The Quality sign-off, the governance view, validation and release, the training record.',
  roles: ['quality'],
  sections: [
    {
      id: 'qa-role',
      title: 'Your part in a change',
      blocks: [
        {
          lede:
            'You are the second pair of eyes. No customer change is approved without a Quality ' +
            'sign-off, and you see the full record of every change, prices excepted.',
        },
        {
          table: {
            head: ['Where', 'What you do'],
            rows: [
              ['Quoted', 'Give the "Quality sign-off". The cockpit asks for it once the customer accepted.'],
              ['Any stage', 'Read the change on "D1" and "Audit" in the Governance group.'],
              ['Assessment', 'Only if the scoping meeting routed Quality. Then you answer the checklist like every department.'],
              ['Validation', 'Watch the validation issues. Read the release checklist (Quality owns no row). Add lessons learned.'],
              ['Training', 'Record attendance for sessions you held or witnessed, publish new versions, keep the roster.'],
            ],
          },
        },
      ],
    },
    {
      id: 'qa-signoff',
      title: 'The Quality sign-off',
      blocks: [
        {
          p:
            'While the change is "Quoted", the "Offer" tab shows two buttons: "PM sign-off" and ' +
            '"Quality sign-off". Once Sales records "Customer accepted", the cockpit\'s "Next step" ' +
            'says "Sign off (PM and Quality)". Approval needs the customer\'s acceptance and both ' +
            'sign-offs.',
        },
        {
          points: [
            ['What you confirm:', 'the process record. The customer\'s acceptance is recorded, the risks are stated, the concerns are settled, and nothing in the audit says the change should not go ahead.'],
            ['You do not see prices, on purpose.', 'Offer prices are shown to Sales, Project Management, the change lead and admins. The "Offer" tab shows you the sign-off without the figures, and money is blanked in the audit and its CSV. Your sign-off is on the process record, not the price.'],
            ['Four eyes:', '"PM and Quality sign-off must be different users". If you signed as PM, somebody else from Quality signs.'],
            ['Only Quality members', '(or an admin) see the Quality sign-off button.'],
          ],
        },
        { shot: 'qa-signoff', alt: 'The customer response block with "Accepted", "PM sign-off ✓" and the "Quality sign-off" button.' },
      ],
    },
    {
      id: 'qa-governance',
      title: 'The governance view: D1 and Audit',
      blocks: [
        {
          p:
            'Quality, Project Management, the change lead and admins see a Governance group in the ' +
            'tab bar with "D1" and "Audit". Nobody else does.',
        },
        {
          points: [
            ['"D1"', 'holds the formal D1 master data and the "Final assessment" gates: "Feasibility", "Budget", "Release". Quality, PM and the lead may edit the master data.'],
            ['"Audit"', 'is the full history of the change: every status move, answer, date move, sign-off and decision, with name and time. The chain is hash-linked and cannot be edited. It can be exported as CSV.'],
          ],
        },
        {
          p:
            'An auditor asking "who objected, and what was done about it" is answered here: the ' +
            'concerns and risks, and the decision that settled them.',
        },
        { shot: 'qa-audit-tab', alt: 'The "Audit" tab of a change with the chain status and a list of entries including a sign-off.' },
      ],
    },
    {
      id: 'qa-assessment',
      title: 'Your assessment, when you are routed',
      blocks: [
        {
          p:
            'For a part change Quality has no assessment task: the five engineering departments ' +
            'assess. When the scoping meeting gives Quality a letter R or A, you answer the ' +
            'checklist like every department.',
        },
        {
          points: [
            ['"Dimensional risk", "Visual risk"', 'are usually the rows Quality has most to say on. A Yes says what has to be checked.'],
            ['Flag a risk on a Yes row', 'with "⚑ Flag risk", type and rating 1 to 3. A worry about a No row goes in with "+ Risk not on the checklist". Every risk starts hidden on the offer; Sales decides whether the customer reads it, and the offer warns while a severity-3 risk is hidden.'],
            ['Submit', 'with "Submit assessment". A risk never blocks it.'],
          ],
        },
      ],
    },
    {
      id: 'qa-validation',
      title: 'Validation issues',
      blocks: [
        {
          p:
            'When a check fails, a member of a department working on the change, PM or the lead ' +
            'presses "Raise issue" and it becomes a validation issue (VI-1, VI-2 and on). The owner ' +
            'department contains it and finds the cause, PM or the lead decides the route, the ' +
            'check is answered again. Release is refused while any issue is open.',
        },
        {
          points: [
            ['Watch the severity.', '"Blocks production" needs containment before anything else, and starts at level 2.'],
            ['Watch the concessions.', 'A "Customer concession" closes only when Sales records "Accepts the deviation" with the customer\'s mail filed into the issue.'],
            ['Watch the cause.', 'A fix route is decided only after the root cause is recorded. A cause without evidence is a guess.'],
          ],
        },
      ],
    },
    {
      id: 'qa-release',
      title: 'Release and lessons learned',
      blocks: [
        {
          p:
            'The "Release" tab shows "Validation checks", "Release checklist", "Lessons learned" ' +
            'and "Release & close". Quality owns no release checklist row: PPAP, the control plan, ' +
            'surface and technical quality and the measurements are APQP\'s rows. Read the rows ' +
            'anyway: "N.a." rows must carry a note that holds up.',
        },
        {
          p:
            'Add your lessons with "+ Add lesson": what happened, the recommendation, the category, ' +
            'type and severity. They land in the "Lessons Learned" register, linked to the change.',
        },
        { shot: 'qa-lessons', alt: 'The "Lessons learned" step with one lesson and the "+ Add lesson" form open.' },
      ],
    },
    {
      id: 'qa-training',
      title: 'Keeping the training record',
      blocks: [
        {
          p:
            'Quality and Project Management keep the ECR training record. On "Training" you see a ' +
            'third tab, "Records".',
        },
        {
          points: [
            ['"Record attendance"', 'for a session you witnessed: person, role, training date, trainer. Somebody else records your own.'],
            ['"Roster"', 'shows who is signed off, who has tasks open and who has not started. "Export CSV" gives the whole history.'],
            ['"Publish a new version"', 'when the software changes what a role has to know. Everybody signed off in that role takes the practical check again. Say what changed in one or two sentences.'],
          ],
        },
        {
          callout:
            'Attendance is not the sign-off. The person still takes the practical check on their ' +
            'own Training page.',
        },
        { shot: 'qa-records-tab', alt: 'The "Records" tab with the tiles "Signed off", "Tasks open", "Not started" and the roster table.' },
      ],
    },
    {
      id: 'qa-mistakes',
      title: 'Common mistakes',
      blocks: [
        {
          points: [
            ['Signing off without reading the record.', 'The sign-off says the acceptance is recorded, the risks are stated and nothing on the record argues against it.'],
            ['Recording attendance for a session that has not happened.', 'The record says somebody was trained who was not.'],
            ['Accepting an "N.a." without a real note.', 'A release checklist row that does not apply still has to say why.'],
            ['Publishing a new version mid-rollout.', 'Everybody in that role is asked to re-take the check at once. Time it.'],
          ],
        },
      ],
    },
  ],
}

export const qualityTasks: PracticeTaskSpec[] = [
  {
    key: 'qa_quality_signoff',
    role: 'quality',
    title: 'Give the Quality sign-off',
    status: 'needs-sandbox',
    screen: { kind: 'offer', change: 'CR-TRAIN-0015' },
    brief:
      'The customer accepted offer v2 of CR-TRAIN-0015 and the PM has signed off. Check the ' +
      'change\'s risks and history, then give the Quality sign-off.',
    why:
      'No customer change is approved without two different people saying yes. Yours is the ' +
      'second.',
    fixture: [
      'CR-TRAIN-0015 quoted, offer v2 accepted, customer_response accepted, pm_signed_by another user.',
      'Trainee acts as a Quality member.',
    ],
    pass: [
      { assert: 'change.quality_signed_by is the trainee', hint: 'The Quality sign-off is not given yet.' },
      { assert: 'change.pm_signed_by is unchanged', hint: 'Only the Quality sign-off was to be given.' },
    ],
  },
  {
    key: 'qa_flag_row_risk',
    role: 'quality',
    title: 'Answer a row and flag its risk',
    status: 'ready',
    replaces: 'qa_answer_checklist_row',
    screen: { kind: 'assessment', department: 'Quality' },
    brief:
      'The scoping meeting routed Quality on CR-TRAIN-0002. The clip tower moves the mating ' +
      'surface to the bumper, and the gap to the bumper is already at its tolerance limit. ' +
      'Answer the row "Dimensional risk" with what has to be checked, and flag the risk on ' +
      'that row at the highest rating.',
    why:
      'A risk named at assessment becomes a check in the plan, and a severity-3 risk is one ' +
      'Sales has to decide on before the offer goes out. A risk nobody wrote down becomes a ' +
      'complaint.',
    fixture: [
      'CR-TRAIN-0002 in assessment with a Quality row (exists today).',
      'Risk types timing, quality, cost (exist today).',
    ],
    pass: [
      { assert: 'dimensional_risk is answered yes with a remark of at least 5 characters', hint: 'The row "Dimensional risk" is unanswered, No, or has no remark.' },
      { assert: 'an open risk concern exists with checklist_key dimensional_risk', hint: 'The risk is not flagged on the "Dimensional risk" row. Use "⚑ Flag risk" on the row.' },
      { assert: 'that risk has severity 3 and a note of at least 10 characters', hint: 'The gap is at its limit: rate it 3 and say what the risk is.' },
    ],
  },
  {
    key: 'qa_add_lesson',
    role: 'quality',
    title: 'Record a lesson learned',
    status: 'needs-sandbox',
    screen: { kind: 'release', change: 'CR-TRAIN-0012' },
    brief:
      'On CR-TRAIN-0012 the first sampling failed because nobody checked the insert radius ' +
      'against the drawing before it was cut. Record the lesson, as a tooling problem, so the ' +
      'next change checks it.',
    why:
      'A lesson that stays in a meeting is learned once. In the register, linked to the change, ' +
      'it is found by the next team that touches the same tool.',
    fixture: [
      'CR-TRAIN-0012 in_validation, no lessons yet.',
      'Trainee acts as a Quality member.',
    ],
    pass: [
      { assert: 'a lesson linked to CR-TRAIN-0012 exists with title and description', hint: 'No lesson is recorded on this change yet.' },
      { assert: 'its recommendation has at least 10 characters', hint: 'Say what the next change should do differently.' },
      { assert: 'its category is tooling', hint: 'The insert radius is a tooling matter: category "Tooling".' },
      { assert: 'its lesson_type is problem (the form\'s default, so this only catches a change away from it)', hint: 'This lesson comes from something that went wrong: type "Problem".' },
    ],
  },
]
