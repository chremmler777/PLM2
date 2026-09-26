import { TASKS_BY_ROLE } from '../../tasks'
import { APP_ADDRESS } from './shared'
import { PRACTICE_TASKS_BY_ROLE } from './index'
import type { PracticeTaskSpec, TrainingRole } from './types'

//: The one-page handouts, one per role: what the printable handout page
//: (pages/TrainingHandoutPage.tsx) renders first, and the source of
//: docs/training/handouts/*.md (handouts.test.ts checks the files match
//: `handoutMarkdown`; run it with WRITE_HANDOUTS=1 to rewrite them).
//:
//: Same house rules as the chapters: plain English, no em-dashes, every UI
//: label in double quotes exactly as the screen shows it.

export type HandoutBlock =
  /** A table; the first column reads as the row's name. */
  | { h2: string; table: { head: string[]; rows: string[][] } }
  /** A list; each item leads with a bold phrase, the rest may be empty. */
  | { h2: string; points: [string, string][] }
  | { h2: string; p: string }

export interface Handout {
  role: TrainingRole
  /** File name under docs/training/handouts/. */
  file: string
  title: string
  /** Who it is for, after "For ". */
  audience: string
  /** The role's manual chapter number. */
  chapter: string
  job: string
  blocks: HandoutBlock[]
}

export const HANDOUTS: Handout[] = [
  {
    role: 'project_management',
    file: 'project-management.md',
    title: 'Project Management',
    audience: 'Project Managers',
    chapter: '03',
    job: 'lead the change from scoping to closed. Every step has its owner; you make sure nothing waits without a reason.',
    blocks: [
      {
        h2: 'Stage by stage',
        table: {
          head: ['Stage', 'You', 'Where'],
          rows: [
            ['Captured', 'Check the capture, set the lead, "Hand over to scoping"', 'cockpit "Next step", "Status"'],
            ['Scoping', 'Impacted set ("Apply selection"), Development confirms; "+ Record a meeting" with the letters R, A, S, C, I and the cost carrier; decide', '"Impacted", "Scoping"'],
            ['In Assessment', 'Chase open departments; "Add a department to the assessment" if one was forgotten; "Take off routing" if one should not assess (waits for approval); "Close assessment → Costing"', '"Assessments", "Blocked by"'],
            ['Costing', 'Check every department priced its part, "Close costing"', '"Costing", "Cost summary"'],
            ['Quoted', '"PM sign-off" (the cockpit asks once "Customer accepted" is recorded)', '"Offer"'],
            ['Timing', '"Create detailed plan from quote plan", teams confirm, "Validate timing"', '"Timing"'],
            ['Implementing', 'One decision per group (the moved block and what it pushed): "Lock all {n}" or "Escalate to customer"', '"Deviations from the baseline"'],
            ['Validation', '"Decide the route" of each validation issue, "Complete lessons step", "Release change", "Close change"', '"Release"'],
          ],
        },
      },
      {
        h2: 'Rules to remember',
        points: [
          ['The letters decide who assesses,', 'not attendance. Proceed needs at least one R or A. "Informed" is notified only, no task.'],
          ['A routing change after the meeting waits for approval.', 'Somebody other than the one who asked decides it. A department up for removal stays on the hook until then, and the change cannot move to costing.'],
          ['Open questions and cancel votes block "Proceed".', 'The asker or you settle them.'],
          ['Quote deadline moves only with "Push back"', 'and a reason.'],
          ['A plan edit before validation makes every confirmation stale.', ''],
          ['After the baseline every date move is a deviation.', 'Decide each group: the change cannot be released while one is open.'],
          ['Four eyes:', 'you never decide the route of an issue you raised yourself. PM and Quality sign-offs are two different people.'],
          ['Name the project team', '(one responsible per department) on each project page.'],
        ],
      },
      {
        h2: 'Side tracks',
        points: [
          ['KTX Weissenburg / Solingen change:', 'only you start it (PM and admins see "Change from" followed by the plant on the start form). You write the description; scoping records the "Departments to inform", no assessment and no cost carrier; "Send information to the team"; approval waits until it is sent; then straight to timing with their SOP as the release deadline. After "Validate timing" press "Inform" followed by the plant.'],
          ['Validation issue:', 'containment first at "Blocks production", root cause before a fix route, at least one fix action.'],
        ],
      },
    ],
  },
  {
    role: 'sales',
    file: 'sales.md',
    title: 'Sales',
    audience: 'Sales',
    chapter: '04',
    job: 'you own the customer. You start the request, build, sign and send the offer, log every round, tell the customer what they must hear later, and keep the rates on the cost sheet.',
    blocks: [
      {
        h2: 'Stage by stage',
        table: {
          head: ['Stage', 'You', 'Where'],
          rows: [
            ['Captured', '"New Change Request": all parts from the same tool, one-line reason, "Customer change", quote deadline, documents', '"Changes"'],
            ['Scoping', 'Answer the team\'s questions, file the customer\'s reply; rejection letter if rejected', '"Scoping"'],
            ['Quote creation', '"Start the offer": "Timing", "Price", "Risks", "Document"; "Send offer" with the receipt date', '"Offer"'],
            ['Quoted', '"+ Record round"; "New version" with what changed; "Customer accepted" with the release deadline, or "Customer declined"', '"Offer", "Negotiation"'],
            ['Timing', '"Confirm timing" for Sales; "Publish plan to customer" once validated and the bank build mode is set', '"Timing"'],
            ['Implementing', 'Tell the customer about escalated deviations (one escalation per group)', '"Timing"'],
            ['Validation', '"Record customer decision" on an issue; "Quote the fix" if the customer pays; tick "Customer informed of the implementation date / first shipment"', '"Release"'],
          ],
        },
      },
      {
        h2: 'Rules to remember',
        points: [
          ['One request per tool family.', ''],
          ['KTX Weissenburg / Solingen changes are started by Project Management.', 'Send those requests to PM.'],
          ['The offer is valid 30 days from the customer\'s receipt.', 'Enter the real receipt date.'],
          ['From v2 on, say what changed.', 'Sending is refused without it.'],
          ['Your vendor choice is binding.', 'Against the department\'s star you give a reason.'],
          ['Every risk starts hidden on the offer.', 'Switch on what the customer reads. The page warns while a severity-3 risk is hidden: state it or price it, knowingly.'],
          ['You answer questions; the asker marks them solved.', ''],
          ['A concession closes only with the customer\'s mail filed into the issue.', ''],
        ],
      },
      {
        h2: 'The offer PDF',
        p:
          'KTX Group US Corp., Toccoa letterhead; offer number is the change number, Q and the ' +
          'version; scope, price (CBD or rough), changeover, draft timing, risks you chose, terms; ' +
          '"This offer is valid for 30 days from receipt". Dates read like "26 Sep 2026" for every ' +
          'customer. "Preview PDF" shows a draft with a DRAFT watermark. Sales signs the offer: the ' +
          'version you send carries your name and title for good (sent by a PM lead or an admin: the ' +
          'project\'s Sales responsible, else the "Sales" line). A draft shows "Signed by (preview)".',
      },
      {
        h2: 'The cost sheet',
        points: [
          ['You keep the rates;', 'Finance and admins may change them too. One hourly rate per department per plant; "New draft", fill the rates, "Publish version" with "Valid from".'],
          ['A change keeps the rates of the day it was created.', 'A later version never changes it, or an offer already sent.'],
          ['An empty rate is no rate:', 'costing shows "No rate in the cost sheet" and the offer is too low.'],
          ['Machines:', '"Sync from MachineDB" lists the presses; a press may carry its own rate.'],
          ['Silao:', 'quotes in USD, pays in MXN, converted with the exchange rate of the version.'],
        ],
      },
    ],
  },
  {
    role: 'engineering',
    file: 'engineering.md',
    title: 'Engineers',
    audience: 'Development, Tool Engineer, Manufacturing Engineer, Process Engineer, APQP and Packaging Engineer',
    chapter: '05',
    job: 'say what the change means for your area, what it costs and how long it takes; then do it, prove it holds and tick your part of the release.',
    blocks: [
      {
        h2: 'Stage by stage',
        table: {
          head: ['Stage', 'You', 'Where'],
          rows: [
            ['In Assessment', 'Every row "Yes" or "No", a Yes with its "Remark"; "⚑ Flag risk" on a Yes row; verdict; "Submit assessment"', '"Assessments"'],
            ['Costing', '"Cost positions": own time, "External · estimate" or "External · vendor quote" ("+ offer" per vendor, star your favorite); machine time on a class or a named press; a lead time on every line', '"Costing"'],
            ['Timing', '"Confirm timing", or "Raise concern" with what does not work and what would', '"Timing"'],
            ['Implementing', '"Progress", "Actual start", "Actual finish" on your blocks; "Book time"; progress reports', '"Timing", "Reports and time booking"'],
            ['Validation', '"Pass" or "Fail" your checks; "Raise issue" on a fail; as owner "Record containment", "Record root cause", "Tick my fix action"', '"Release"'],
            ['Release', 'Your checklist rows "Done", or "N.a." with a note', '"Release"'],
          ],
        },
      },
      {
        h2: 'Department specifics',
        points: [
          ['Development:', '"Confirm impact (Development)" at scoping; extra row "Article design update"; triage every new index ("Full ECR", "Attach to an open change", "Engineering review", "Administrative"). Release: index, drawing and 3D data, spare parts.'],
          ['Tool Engineer:', 'tools and molds; "Part weight" estimate at costing. Validation: measures the cycle time ("Measured cycle time", seconds) and the part weight. Release: tool and equipment data, part weight, "Cycle time: changed (new value entered) or confirmed unchanged" ("Changed" needs the new seconds; the row shows your validation measurement).'],
          ['Manufacturing Engineer:', 'equipment. No release row, no cycle time (the cycle time is the Tool Engineer\'s).'],
          ['APQP:', 'gauges; extra rows "PFMEA update", "Control plan update". Release: "Process stable: SPC Cm > 1.67" (APQP alone; Cm optional, above 1.67), "Surface quality confirmed", "Technical quality confirmed", "Measurements confirmed, measurement report on file", "PPAP / initial sample documentation complete, customer approval received (ISIR / PSW)", "Control plan / inspection plan updated".'],
          ['Process Engineer:', 'assesses when the scoping meeting gives it a letter. Keeps the process details (parameters, PFMEA, work instructions) in the process database (PDB) and confirms them there. No release row and no cycle time measurement.'],
          ['Packaging Engineer:', '"Packaging impacted?" first; No is a complete answer. Release: "Packaging instruction updated".'],
        ],
      },
      {
        h2: 'Rules to remember',
        points: [
          ['A Yes without a remark cannot be costed or planned.', ''],
          ['"Rest to No" is visible to reviewers.', 'Look at the rows first.'],
          ['"Not feasible" needs the change PPT.', 'Risks never block the submit.'],
          ['A line without a rate is not counted.', 'Tell Sales, who keep the cost sheet. A change is priced with the rates valid on the day it was created.'],
          ['A failed check needs a reason.', 'A fail without one is not a check.'],
          ['After the baseline only PM, Sales, Scheduling and the lead move dates.', 'Tell PM when a date will not hold.'],
        ],
      },
    ],
  },
  {
    role: 'scheduling',
    file: 'scheduling.md',
    title: 'Scheduling',
    audience: 'Scheduling',
    chapter: '06',
    job: 'decide how the change reaches the line without the customer running short, help build and confirm the plan, and close out ERP and stock.',
    blocks: [
      {
        h2: 'Stage by stage',
        table: {
          head: ['Stage', 'You', 'Where'],
          rows: [
            ['In Assessment', 'Only if routed at scoping: answer the checklist, "Cycle time change" is yours to judge', '"Assessments"'],
            ['Costing to Quoted', 'You may edit the quote plan with PM and Sales, until approval', '"Offer", "Timing" step'],
            ['Timing', '"Bank build plan" (often already set from the accepted offer: check it): "Running change" or "Planned scrap" (with "Scrap quote price", the total) and a "Plan note"; turn the "Bank build (idea)" into a real block; "Confirm timing"; "Validate timing" once everyone confirmed', '"Timing"'],
            ['Implementing', 'Progress on your own blocks; a date move asks "Why does this move?"', '"Timing"'],
            ['Validation', '"ERP, BOM and routing updated", "Old stock handled as agreed (bank consumed or scrapped)"', '"Release"'],
          ],
        },
      },
      {
        h2: 'Rules to remember',
        points: [
          ['No idea block survives validation.', '"Validate timing" stays disabled until each is real or deleted.'],
          ['The bank build ends before the tool downtime starts.', 'The plan warns if it does not.'],
          ['Your own plan edit makes your confirmation stale too.', 'Confirm after the last edit.'],
          ['After the baseline every move is a deviation.', 'Write a reason the customer could read. The move and the blocks it pushed are decided as one group.'],
          ['Only Scheduling, PM, the change lead or an admin set the bank build plan.', 'Sales publishes it.'],
        ],
      },
      {
        h2: 'KTX Weissenburg / Solingen changes',
        p:
          'Project Management starts them. No assessment and no offer: scoping records which ' +
          'departments are informed, each confirms "Read and understood", and the change goes to ' +
          'timing with the mother plant\'s SOP as the release deadline. Your bank build planning is ' +
          'the first real work. Their MS Project file seeds the plan at approval; "Import MS ' +
          'Project" loads one later.',
      },
    ],
  },
  {
    role: 'quality',
    file: 'quality.md',
    title: 'Quality',
    audience: 'Quality',
    chapter: '07',
    job: 'the second pair of eyes. No customer change is approved without a Quality sign-off, and you see the full record of every change.',
    blocks: [
      {
        h2: 'Where you act',
        table: {
          head: ['When', 'You', 'Where'],
          rows: [
            ['Quoted, customer accepted', '"Quality sign-off" (a different person from the PM sign-off): you confirm the process record, not the prices, which you do not see (on purpose)', '"Offer"'],
            ['Any stage', 'Read the D1 master data and gates ("Feasibility", "Budget", "Release") and the full history', '"D1", "Audit" (Governance group)'],
            ['In Assessment', 'Only if routed at scoping: answer the checklist, "Dimensional risk" and "Visual risk" first', '"Assessments"'],
            ['Validation', 'Watch the validation issues; read the release checklist (Quality owns no row: PPAP, control plan, surface and technical quality and measurements are APQP\'s); "+ Add lesson"', '"Release"'],
            ['Training', '"Record attendance", "Roster", "Export CSV", "Publish a new version"', '"Training", "Records"'],
          ],
        },
      },
      {
        h2: 'Rules to remember',
        points: [
          ['"PM and Quality sign-off must be different users".', ''],
          ['Approval needs three things:', 'the customer\'s acceptance, the PM sign-off, the Quality sign-off.'],
          ['The audit trail cannot be edited.', 'It is the answer to "who decided, and why".'],
          ['No release with an open validation issue.', 'A concession closes only with the customer\'s mail filed.'],
          ['"N.a." on a release checklist row needs a note that holds up.', 'Check it on APQP\'s rows too.'],
          ['Attendance is not the sign-off.', 'The person still takes the practical check. Nobody records their own attendance.'],
          ['Publishing a new version asks everybody in that role to re-take the check.', 'Time it.'],
        ],
      },
    ],
  },
  {
    role: 'finance',
    file: 'finance.md',
    title: 'Finance',
    audience: 'Finance',
    chapter: '08',
    job: 'check the cost sheet Sales keeps; you may change it too. Every hour, machine hour and sampling trial on a change is priced from it.',
    blocks: [
      {
        h2: 'The cost sheet',
        table: {
          head: ['Tab', 'Holds'],
          rows: [
            ['"Rates"', 'One hourly rate per department and plant; an empty rate is no rate; the effective rate includes the overhead'],
            ['"Machines"', 'Hourly rate per machine class (by tonnage); the presses from MachineDB ("Sync from MachineDB"), each with an optional rate of its own'],
            ['"Sampling"', 'Price of one trial per machine class'],
            ['"Overheads"', 'Personnel overhead, percent or per hour'],
          ],
        },
      },
      {
        h2: 'Changing a rate',
        p:
          'Sidebar, Setup, "Cost sheet" (Setup shows for the admin and engineer roles; everybody ' +
          'else opens the address ending in /cost-sheet). "New draft" (a copy of the latest ' +
          'published version), edit, check "Changes vs previous", "Publish version" with "Valid ' +
          'from" (after the latest published version\'s) and a note. Published versions are ' +
          'frozen. Sales, Finance and admins may edit.',
      },
      {
        h2: 'What the rates do',
        points: [
          ['A change is priced with the rates valid on the day it was created.', 'Costing shows the version; each line stores its rate and version. A later version never changes an existing change.'],
          ['"No rate in the cost sheet"', 'on a line: it is not counted. Fill the rate in a version valid on the change\'s creation date.'],
          ['P&L actuals', 'use the rate valid on the booking date. Prices on a change are shown to Sales, Project Management, the change lead and admins: unless you lead a change, Finance sees none. That is intended: you check the rates, not the offers.'],
          ['Currency', 'comes from the plant. Silao quotes in USD and pays in MXN: the version\'s USD/MXN exchange rate converts MXN rates and actual costs, and every conversion names its rate. Other currencies are not converted.'],
        ],
      },
      {
        h2: 'Rules to remember',
        points: [
          ['A rate takes effect from its date.', 'Publish before, not after.'],
          ['Backdating', '("Publish backdated anyway"): changes created since then (lines without a rate) and time booked since then are priced with the new version. Lines already priced keep their rate.'],
          ['Nothing to publish without a difference.', 'Publishing an unchanged draft is refused.'],
          ['"Review every {n} months".', 'When due: "Cost sheet review due" on the cost sheet and "Review the cost sheet" in "My Tasks", for Sales and for you.'],
          ['"Plant currencies":', '"Confirm" each one, or "Change" it if the location guessed wrong.'],
        ],
      },
    ],
  },
]

export function handoutFor(role: string): Handout | undefined {
  return HANDOUTS.find((h) => h.role === role)
}

/** The practical check of a role: what this build runs, and what comes later. */
export function practiceOf(role: string): { active: { key: string; title: string }[]; coming: PracticeTaskSpec[] } {
  const active = (TASKS_BY_ROLE[role] ?? []).map((t) => ({ key: t.key, title: t.title }))
  const keys = new Set(active.map((t) => t.key))
  const coming = (PRACTICE_TASKS_BY_ROLE[role as TrainingRole] ?? []).filter((t) => !keys.has(t.key))
  return { active, coming }
}

/** The handout as markdown: what docs/training/handouts/<file> holds. */
export function handoutMarkdown(h: Handout): string {
  const out: string[] = [
    `# ECR handout: ${h.title}`,
    '',
    `For ${h.audience}. One page for the session and the desk; the full chapter is in PLM2 ` +
      `under **Training**, "Manual", chapter ${h.chapter}. Address: ${APP_ADDRESS}`,
    '',
    `**Your job:** ${h.job}`,
  ]
  for (const b of h.blocks) {
    out.push('', `## ${b.h2}`, '')
    if ('table' in b) {
      out.push(`| ${b.table.head.join(' | ')} |`, `|${b.table.head.map(() => '---').join('|')}|`)
      for (const r of b.table.rows) out.push(`| ${r.join(' | ')} |`)
    } else if ('points' in b) {
      for (const [lead, rest] of b.points) out.push(`- **${lead}**${rest ? ` ${rest}` : ''}`)
    } else {
      out.push(b.p)
    }
  }
  const { active, coming } = practiceOf(h.role)
  out.push('', '## Your practical check', '')
  active.forEach((t, i) => out.push(`${i + 1}. ${t.title}.`))
  if (coming.length > 0) {
    out.push('', 'Coming, once the training copy can run them:', '')
    for (const t of coming) out.push(`- ${t.title}.`)
  }
  out.push(
    '',
    'Training is recorded, not blocking. Confirm your session on the Training page ' +
      '("Confirm your training"), then take the check.',
    '',
  )
  return out.join('\n')
}
