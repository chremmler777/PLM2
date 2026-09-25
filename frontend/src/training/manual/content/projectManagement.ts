import { SEED } from '../../sandbox/state'
import type { ContentChapter, PracticeTaskSpec } from './types'

//: Chapter 03, Project Management. pm-takeover, pm-priority, pm-scoping and
//: pm-plan replace the stubs of the same id in ../chapters.tsx.

export const pmChapter: ContentChapter = {
  id: 'pm',
  number: '03',
  title: 'Project Management',
  summary: 'Leading a change: scoping, deadlines, costing, the plan, validation issues, closing.',
  roles: ['project_management'],
  sections: [
    {
      id: 'pm-role',
      title: 'Your part in a change',
      blocks: [
        {
          lede:
            'You lead the change from scoping to closed. You do not do every step, but you make ' +
            'sure every step has its owner and nothing waits without a reason.',
        },
        {
          table: {
            head: ['Stage', 'What you do'],
            rows: [
              ['Captured', 'Take over with "Hand over to scoping". Set the lead; as the lead, set the priority and check the quote deadline.'],
              ['Scoping', 'Build the impacted set, run the scoping meeting, decide.'],
              ['In Assessment', 'Chase the open departments, add a forgotten one, decide on "Not our responsibility", then "Close assessment → Costing".'],
              ['Costing', 'Watch every department price its part, then "Close costing".'],
              ['Quoted', 'Give the "PM sign-off". The cockpit asks for it once the customer accepted.'],
              ['Timing', 'Create the detailed plan, get every team to confirm, "Validate timing".'],
              ['Implementing', 'Lock or escalate each deviation. The change cannot be released while one is open.'],
              ['Validation', 'Decide the route of each validation issue, complete the lessons step, release and close.'],
            ],
          },
        },
        {
          p:
            'You are usually the change lead. The lead defaults to the Project Manager named on the ' +
            'project\'s "Project team" card. Name that team for each project you run: it decides ' +
            'whose badge each task counts on.',
        },
      ],
    },
    {
      id: 'pm-takeover',
      title: 'Taking over a captured change',
      blocks: [
        {
          steps: [
            { title: 'Read the capture', body: 'Reason, affected items, the customer\'s documents. The "Next step" card lists what is still missing before scoping can start.' },
            { title: 'Check the lead', body: 'On the "Status" card: "Lead", or "No lead assigned". Pick one with "Pick a lead", or "Me". Scoping waits for a lead.' },
            { title: 'Hand over', body: '"Hand over to scoping". Sales and the lead can still correct the capture fields afterwards.' },
          ],
        },
        {
          p:
            'If the request is dead on arrival, Sales can reject it straight from capture, with a ' +
            'reason. It does not have to pass through scoping.',
        },
        { shot: 'pm-next-step-capture', alt: 'The "Next step" card on a captured change listing "Missing before scoping can start:" and the button "Hand over to scoping".' },
      ],
    },
    {
      id: 'pm-priority',
      title: 'Priority and the deadlines',
      blocks: [
        {
          points: [
            ['"Priority"', 'orders everybody\'s task list: "Low", "Medium", "High", "Critical". Only the change lead sets it. Critical is for a stopped line or a safety issue.'],
            ['"Quote deadline"', 'is when the customer expects the offer. Sales sets it at capture. It is active until the offer is sent.'],
            ['"Release deadline"', 'is born when the customer accepts. It is active from then on.'],
          ],
        },
        {
          p:
            'After capture the quote deadline moves only with "Push back", and the dialog asks "Why ' +
            'can the quote deadline not be met? (required, audited)". The deadline has one owner; ' +
            'a department that sees it slip tells you, and you record the push back.',
        },
        { shot: 'pm-status-card', alt: 'The "Status" card with "Priority", "Lead" and the quote deadline chip showing "Quote in 6 d".' },
      ],
    },
    {
      id: 'pm-scoping',
      title: 'The scoping meeting',
      blocks: [
        { h3: 'Before the meeting: the impacted set' },
        {
          p:
            'On the "Impacted" tab pick the impacted items in the impact tree and press "Apply ' +
            'selection". Suggestions mark parent assemblies that are structurally affected. Then ' +
            'Development confirms with "Confirm impact (Development)". Nothing is assessed until the ' +
            'set is confirmed, and a later edit clears the confirmation.',
        },
        { shot: 'pm-impact-tree', alt: 'The impact tree with the lead item, two suggested assemblies and "Confirm impact (Development)".' },
        { h3: 'The meeting itself' },
        {
          steps: [
            { title: 'Record it', body: '"+ Record a meeting" on the "Scoping" tab: channel, "Meeting date", "Participants". Attendance only, not responsibility.' },
            { title: 'Set who assesses', body: 'Under "Impacted departments" give each department a letter: "Responsible (assesses)", "Accountable (assesses)", "Supports", "Consulted / informed" or "Not involved". The standard routing is pre-selected; the room overrules it.' },
            { title: 'Confirm the cost carrier', body: '"Cost carrier" is required before the assessment can start. Flipping it is audited and Sales is notified.' },
            { title: 'Decide', body: '"Proceed & start assessment", "Needs more info" or "Reject". Proceed starts the assessment for every R and A department.' },
          ],
        },
        {
          callout:
            'Open questions and cancel votes block "Proceed". Risks do not: a change goes ahead with ' +
            'its risks on the record. The person who raised a question or vote, or you as PM, ' +
            'settles it first. "Needs more info" keeps the change in scoping and gives Sales the ' +
            'task to get the answer from the customer.',
          tone: 'warn',
        },
        { shot: 'pm-scoping-meeting', alt: 'The scoping meeting form with RASIC letters per department, the cost carrier and "Save meeting".' },
      ],
    },
    {
      id: 'pm-assessment',
      title: 'Steering the assessment',
      blocks: [
        {
          points: [
            ['Who is still owed:', '"Blocked by" lists the departments that have not submitted.'],
            ['A forgotten department:', '"Add a department to the assessment" with a letter and a reason. It takes effect once somebody other than you approves it: the change lead, or another Project Manager if you are the lead (four eyes).'],
            ['"Not our responsibility":', 'a department can decline. The lead decides; if rejected, the assessment stays with them.'],
            ['"Not feasible":', 'the "Next step" card offers "Reject change", "Back to scoping" or "Override with a reason". An override is a deviation somebody else approves.'],
            ['All answered:', '"Close assessment → Costing". The confirm dialog lists every verdict and open risk.'],
          ],
        },
      ],
    },
    {
      id: 'pm-costing',
      title: 'Running costing',
      blocks: [
        {
          p:
            'You see every department\'s block and the "Cost summary". Check that every department ' +
            'on the hook has entered its input and every line has a rate. The "Close costing" dialog ' +
            'lists anything missing.',
        },
        {
          p:
            'Closing costing freezes the numbers and hands the change to Sales. If a number has to ' +
            'change later, "Reopen costing" asks "Which numbers have to change? (required, audited)".',
        },
        { shot: 'pm-cost-summary', alt: 'The "Cost summary" card with "By department" totals and the "Timing" block showing "Longest lead time".' },
      ],
    },
    {
      id: 'pm-signoff',
      title: 'The PM sign-off',
      blocks: [
        {
          p:
            'While the change is "Quoted", the "Offer" tab shows "PM sign-off" and "Quality ' +
            'sign-off". The cockpit asks for them once Sales has recorded "Customer accepted". ' +
            'Approval needs the customer\'s acceptance and both sign-offs. The two sign-offs must ' +
            'come from two different people.',
        },
        { shot: 'pm-signoff', alt: 'The customer response block with "Accepted", "PM sign-off ✓" and "Quality sign-off" still open.' },
      ],
    },
    {
      id: 'pm-plan',
      title: 'Timing and the plan',
      blocks: [
        {
          steps: [
            { title: 'Create the detailed plan', body: '"Create detailed plan from quote plan" copies every block of the quote plan, links and ideas included.' },
            { title: 'Refine it with the teams', body: 'Real durations, owners, links. Every edit before validation makes the teams\' confirmations stale.' },
            { title: 'Get every team to confirm', body: 'The "Team confirmation" panel counts "{n} of {m} confirmed". A concern comes with a note: fix the plan, then ask again.' },
            { title: '"Validate timing"', body: 'Sets the baseline. It stays disabled while anything is open, and says what: plan errors, idea blocks, a concern, a missing confirmation.' },
          ],
        },
        { shot: 'pm-validate-timing', alt: 'The Timing tab steps "Detailed plan", "Team confirmation", "Validate timing" with the button enabled.' },
        { h3: 'Deviations' },
        {
          p:
            'After the baseline every date move is listed under "Deviations from the baseline" with ' +
            'its reason, slip and effect on the finish. Each one needs your decision. Open ' +
            'deviations do not stop the work, but the change cannot be released while one is open.',
        },
        {
          table: {
            head: ['Button', 'Means'],
            rows: [
              ['"Lock"', 'Accepted internally. No customer impact, for example a slip the buffer absorbs.'],
              ['"Escalate to customer"', 'Sales tells the customer. This opens a customer escalation.'],
            ],
          },
        },
        { shot: 'pm-deviations', alt: '"Deviations from the baseline" with one open row, its reason, "+3 d" slip, "Lock" and "Escalate to customer".' },
        { h3: 'Changes from KTX Weissenburg or KTX Solingen' },
        {
          p:
            'At scoping, send the information to every team that has to act ("Send information to" ' +
            'the chosen departments). Approval waits until it is sent. After "Validate timing" press ' +
            '"Inform" followed by the plant to record that you sent them the baseline.',
        },
      ],
    },
    {
      id: 'pm-issues',
      title: 'Validation issues: deciding the route',
      blocks: [
        {
          p:
            'When a check fails, a member of a department working on the change, you or the lead ' +
            'presses "Raise issue" on it. The issue names an owner department, which contains it ' +
            'and finds the cause. You, or the lead, decide the route with "Decide the route".',
        },
        {
          points: [
            ['Four eyes:', 'if you raised the issue yourself, another PM or the lead decides.'],
            ['Containment first', 'when the severity is "Blocks production". Root cause first for every route except a concession.'],
            ['A fix route', '("Internal rework", "Supplier rework", "Design change") needs at least one fix action. The change goes back to implementation and a recovery group appears in the plan.'],
            ['The reason', 'is recorded on the change and on every plan deviation the recovery causes.'],
          ],
        },
        {
          p:
            'Escalation levels rise on their own. Project Management (or an admin) can lower a ' +
            'level with a reason ("Lower to L1" on an L2 issue), and you close an issue by hand ' +
            'only when it has no linked check.',
        },
        { shot: 'pm-route-dialog', alt: 'The "Decide the route for VI-1" dialog with "Internal rework" selected, one fix action and a reason.' },
      ],
    },
    {
      id: 'pm-release',
      title: 'Release and close',
      blocks: [
        {
          steps: [
            { title: 'Lessons learned', body: 'Make sure the team adds its lessons. Then "Complete lessons step", or give the reason there are none.' },
            { title: 'Release', body: '"Release change" once the release step shows no blocker: every validation check passed, no open validation issue, every impacted revision through its check workflow, every checklist row answered, the lessons step completed and no open plan deviation.' },
            { title: 'Read the summary', body: 'Plan against actual timing, offer against actual cost. The difference is the lesson for the next quote.' },
            { title: 'Close', body: '"Close change".' },
          ],
        },
      ],
    },
    {
      id: 'pm-mistakes',
      title: 'Common mistakes',
      blocks: [
        {
          points: [
            ['Proceeding with nobody on R or A.', 'Refused: the dialog shows "No department is marked R or A: nobody assesses".'],
            ['Editing the impacted set after Development confirmed it.', 'The confirmation is cleared and the change waits for Development again.'],
            ['Validating the timing with a stale confirmation.', 'The button stays disabled. Ask the team to confirm the current plan.'],
            ['Leaving deviations open.', 'They do not stop the work, which is why they get forgotten, but the change cannot be released while one is open. Decide each one.'],
            ['Deciding the route of an issue you raised.', 'Refused. Ask the lead or another PM.'],
            ['No project team named.', 'Then the whole department counts every task and nobody feels it is theirs.'],
          ],
        },
      ],
    },
  ],
}

export const pmTasks: PracticeTaskSpec[] = [
  {
    key: 'pm_set_priority',
    role: 'project_management',
    title: 'Set priority and the quote deadline',
    status: 'ready',
    screen: { kind: 'change-status', changeId: SEED.changeCaptured },
    brief:
      'CR-TRAIN-0001 (Grille Carrier) was escalated by the customer this morning. Set its ' +
      'priority to High, and give it a quote deadline: the customer expects the quote within ' +
      'two weeks.',
    why:
      'Priority orders everybody\'s task list, and the quote deadline is the date every ' +
      'department is measured against.',
    fixture: ['CR-TRAIN-0001 captured, priority medium, no quote deadline (exists today).'],
    pass: [
      { assert: 'change.priority is high', hint: 'The priority is not High yet. Critical is for a stopped line or a safety issue.' },
      { assert: 'change.required_by_date is set, 0 to 15 days from today', hint: 'The quote deadline should fall within the next two weeks.' },
    ],
  },
  {
    key: 'pm_scoping_proceed',
    role: 'project_management',
    title: 'Record the scoping meeting and proceed',
    status: 'needs-sandbox',
    screen: { kind: 'scoping', change: 'CR-TRAIN-0005' },
    brief:
      'The team met today about CR-TRAIN-0005. Tool Engineer and Development assess, APQP ' +
      'supports, Manufacturing Engineer is kept informed, Packaging is not involved. The ' +
      'customer pays. Record the meeting and start the assessment.',
    why:
      'The letters decide who assesses, not who was in the room. A wrong letter is a ' +
      'department that never gets its task, or one that gets a task it cannot answer.',
    fixture: [
      'CR-TRAIN-0005 in scoping, customer_relevant true, lead set, required_by_date set, at least one impacted item, impacted set confirmed by Development, no open concerns.',
      'Departments Development, Tool Engineer, APQP, Packaging Engineer, Manufacturing Engineer.',
      'Trainee acts as a Project Management member.',
    ],
    pass: [
      { assert: 'a meeting exists with decision proceed', hint: 'No meeting with the decision "Proceed & start assessment" yet.' },
      { assert: 'department_rasic gives Tool Engineer and Development R or A', hint: 'Tool Engineer and Development assess: give them R or A.' },
      { assert: 'APQP is S and Packaging Engineer is not R or A', hint: 'APQP supports and Packaging is not involved. Check their letters.' },
      { assert: 'Manufacturing Engineer is C', hint: 'Manufacturing Engineer is kept informed: "Consulted / informed".' },
      { assert: 'the cost carrier is customer', hint: 'The customer pays: the cost carrier is "Customer (customer relevant)".' },
      { assert: 'change.status is in_assessment', hint: 'The change has not moved to assessment. Did the meeting decide to proceed?' },
    ],
  },
  {
    key: 'pm_decide_deviation',
    role: 'project_management',
    title: 'Decide two deviations',
    status: 'needs-sandbox',
    screen: { kind: 'timing', change: 'CR-TRAIN-0004' },
    brief:
      'Two blocks slipped after the baseline. The toolmaker is three days late, but the safety ' +
      'buffer absorbs it and the finish does not move. The supplier of the new insert is two ' +
      'weeks late and the finish moves past the release deadline. Decide both.',
    why:
      'An open deviation does not stop the work, so it is easy to forget, but the change cannot ' +
      'be released while one is open. The customer learns about a late finish from us, through ' +
      'Sales, or from their receiving dock.',
    fixture: [
      'CR-TRAIN-0004 in_implementation, baseline set.',
      'Trainee acts as a Project Management member.',
      'Deviation A: toolmaker block +3 d, finish_impact_days 0, open.',
      'Deviation B: supplier block +14 d, finish past release_due_date, open.',
    ],
    pass: [
      { assert: 'deviation A status is locked', hint: 'The toolmaker slip is absorbed by the buffer: accept it internally with "Lock".' },
      { assert: 'deviation B status is escalated with a non-empty note', hint: 'The supplier slip moves the finish past the release deadline: the customer has to hear it. Say in a sentence what Sales tells them.' },
    ],
  },
  {
    key: 'pm_route_issue',
    role: 'project_management',
    title: 'Decide the route of a validation issue',
    status: 'needs-sandbox',
    screen: { kind: 'validation-issue', change: 'CR-TRAIN-0008' },
    brief:
      'VI-1 on CR-TRAIN-0008: the clip tower breaks at the first sampling. Tool Engineer ' +
      'contained it and found the cause, a sharp corner in the new insert. Our own toolshop ' +
      'rounds it in three days. Decide the route.',
    why:
      'The route decides where the change goes next, who does what and whether the customer ' +
      'hears about it. It is decided by somebody who did not raise the issue.',
    fixture: [
      'CR-TRAIN-0008 in_validation, VI-1 raised by another user, severity 2, containment and root cause recorded.',
      'Trainee acts as a Project Management member.',
      'Detailed plan with baseline and a validation block.',
    ],
    pass: [
      { assert: 'VI-1 route is internal_rework', hint: 'Our own toolshop fixes it: the route is "Internal rework".' },
      { assert: 'route_reason has at least 10 characters', hint: 'Give the reason. It is recorded on the change and on the plan deviations.' },
      { assert: 'VI-1 has at least one open fix action with a due date', hint: 'A fix route needs at least one fix action. Give it a due date so the recovery block has a real length.' },
    ],
  },
]
