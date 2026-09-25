import type { ContentChapter } from './types'

//: Chapters 01 and 02, read by everybody. Section ids that exist as stubs in
//: ../chapters.tsx (basics-why, basics-owners, basics-finding, flow-capture,
//: flow-scoping, flow-assessment, flow-costing, flow-implementation,
//: flow-validation) replace those stubs; the others are new sections.

export const APP_ADDRESS = 'https://apps.ad.us.ktx.group/plm2/'

export const basicsChapter: ContentChapter = {
  id: 'basics',
  number: '01',
  title: 'Why the ECR process, and who owns what',
  summary: 'One place for every engineering change. The same information for everyone.',
  sections: [
    {
      id: 'basics-why',
      title: 'What the change process is for',
      blocks: [
        {
          lede:
            'A customer changes a part. We have to know what it touches, whether we can do it, ' +
            'what it costs, what we charge, when it is done and that it holds. The change page ' +
            'keeps all of that in one record.',
        },
        {
          points: [
            ['One record.', 'The request, the assessments, the costs, the offer, the plan and the release live on one change page.'],
            ['One owner per step.', 'The page says who acts next and what it is waiting for.'],
            ['Nothing gets lost.', 'Every answer, date move and decision carries a name and a time. The history cannot be edited.'],
            ['Offer against reality.', 'At the end each change compares what we offered with what it cost and how long it took.'],
          ],
        },
        {
          callout:
            'Training is recorded for the audit. It does not block any change action. You can work ' +
            'on a change before your practical check is done.',
          title: 'Recorded, not blocking',
        },
      ],
    },
    {
      id: 'basics-access',
      title: 'Where it lives, and how you get in',
      blocks: [
        {
          points: [
            ['Address:', APP_ADDRESS],
            ['Sign in', 'with your KTX account. Nothing to install.'],
            ['Your name is the record.', 'Everything you enter is stamped with your account. Never work in a colleague\'s session.'],
            ['Version number', 'next to the logo. Quote it when you report a problem.'],
          ],
        },
        { shot: 'basics-sidebar', alt: 'The sidebar with "Changes", "Process Flow", "P&L", "My Tasks" and "Training" visible.' },
      ],
    },
    {
      id: 'basics-owners',
      title: 'Who owns which step',
      blocks: [
        {
          table: {
            head: ['Role', 'Owns'],
            rows: [
              ['Sales', 'Starting the request, the offer, every contact with the customer, the customer\'s answer.'],
              ['Project Management', 'Leading the change: scoping, deadlines, closing costing, the plan, the route of a validation issue, closing the change.'],
              ['Development', 'Locking what is impacted, deciding the route of every new customer index, the drawing and 3D data.'],
              ['Tool, Manufacturing, Process, APQP, Packaging', 'Assessing, costing and doing their own part of the work, and their own release checks.'],
              ['Scheduling', 'How the change reaches the line (bank build), the plan with PM and Sales, ERP and old stock.'],
              ['Quality', 'The Quality sign-off before approval, the governance view (D1, Audit), the training record.'],
              ['Finance', 'The cost sheet: every rate that prices a change.'],
            ],
          },
        },
        {
          p:
            'Sales owns the customer. Anyone can file a customer mail on a change, but what goes ' +
            'to the customer goes through Sales.',
        },
      ],
    },
    {
      id: 'basics-team',
      title: 'Project team: one responsible per role',
      blocks: [
        {
          p:
            'On every project, the Project Manager names one responsible per department on the ' +
            '"Project team" card of the project page. The responsible leads that department\'s ' +
            'tasks on the project\'s changes.',
        },
        {
          points: [
            ['Responsible:', 'the task counts on your badge and in "My Tasks", and the notification goes to you.'],
            ['Everyone else in the department is backup:', 'you see the same task, marked "Backup" with "Main:" and the responsible\'s name. You can act on it. It does not count on your badge.'],
            ['When a backup acts,', 'the record says who acted for whom.'],
            ['No responsible set:', 'the whole department counts, as before.'],
          ],
        },
        { shot: 'basics-project-team', alt: 'The "Project team" card with one responsible per department and one row "Unassigned".' },
        { shot: 'basics-backup-row', alt: 'A task row in "My Tasks" with the "Backup" chip and "Main:" followed by a name.' },
      ],
    },
    {
      id: 'basics-finding',
      title: 'Finding your work: My Tasks and the change page',
      blocks: [
        {
          p:
            '"My Tasks" in the sidebar is everything waiting on you, in one list. The number at the ' +
            'top counts only the tasks you lead. Backup tasks follow underneath, muted.',
        },
        { shot: 'basics-my-tasks', alt: '"My Tasks" with "Open tasks", a "+2 as backup" note and a "New indexes" section.' },
        { h3: 'The change page' },
        {
          p:
            'Open a change and read the cockpit at the top before anything else. It answers the ' +
            'three questions every visit starts with.',
        },
        {
          table: {
            head: ['Card', 'Answers'],
            rows: [
              ['"Your actions"', 'What you have to do on this change. Backup items sit under "As backup".'],
              ['"Blocked by"', 'What the change is waiting for, and on whom. "Nothing blocking" when it is free.'],
              ['"Next step"', 'The button that moves the change on, for whoever may press it.'],
              ['"Status"', 'Priority, the lead, the active deadline.'],
            ],
          },
        },
        { shot: 'basics-cockpit', alt: 'The change cockpit with "Your actions", "Blocked by", "Next step" and "Status" filled in.' },
        {
          p:
            'Below the cockpit are the tabs: "Overview", "Scoping", "Impacted", "Assessments", ' +
            '"Costing", "Offer", "Timing", "Release". A tab unlocks when the change reaches its ' +
            'stage, and the page opens on the tab of the current stage. "D1" and "Audit" sit in the ' +
            'Governance group for the lead, Project Management, Quality and admins.',
        },
      ],
    },
  ],
}

export const flowChapter: ContentChapter = {
  id: 'flow',
  number: '02',
  title: 'A change, end to end',
  summary: 'From the customer\'s request to the released part, and the three side tracks.',
  sections: [
    {
      id: 'flow-overview',
      title: 'The stages at a glance',
      blocks: [
        {
          table: {
            head: ['Stage (as the page shows it)', 'What happens, who acts'],
            rows: [
              ['Captured', 'Sales starts the request with the reason, the parts and the customer\'s documents.'],
              ['Scoping', 'PM meets the team, Development locks the impacted set, the room decides who assesses.'],
              ['In Assessment', 'The routed departments answer the checklist, flag risks and give a verdict.'],
              ['Costing', 'The departments price their part with a lead time on every line. PM closes costing.'],
              ['Quote creation', 'Sales builds the offer: rough timing, price, risks, document.'],
              ['Quoted', 'The offer is with the customer. Rounds and new versions are logged. The customer accepts or declines.'],
              ['Timing (approved)', 'The detailed plan, the bank build, every team confirms, "Validate timing" sets the baseline.'],
              ['Implementing', 'The work. Progress on the plan. Every date move is a deviation with a reason.'],
              ['Validation', 'Checks, the release checklist, lessons learned. A failed check becomes a validation issue.'],
              ['Released, Closed', 'The change is live. PM reads the summary and closes it.'],
            ],
          },
        },
        { shot: 'flow-stepper', alt: 'The lifecycle stepper on a change in "Quoted", with the hint "Offer sent to customer".' },
        {
          p:
            'The "Process Flow" page in the sidebar draws the same flow with its gates, loops and ' +
            'side tracks.',
        },
      ],
    },
    {
      id: 'flow-capture',
      title: 'Capture',
      blocks: [
        {
          p:
            'Sales starts the request with "New Change Request" on the "Changes" page, or "Start ' +
            'change request" on a part. Project Management may start one too.',
        },
        {
          points: [
            ['Affected items:', 'pick every part that changes with the same tool. The first is the lead item; the title is built from it.'],
            ['Short description:', 'one line, what the problem is. Detail belongs in the attachments.'],
            ['Who carries the cost:', '"Customer change" for anything the customer pays.'],
            ['Quote deadline and customer documents:', 'optional at the start, but scoping waits for them.'],
          ],
        },
        {
          p:
            'Before PM can take over, the capture needs a description, at least one attachment and, ' +
            'for a customer change, the quote deadline. The form says what is missing: "Not ready ' +
            'to hand over to scoping yet, missing:".',
        },
      ],
    },
    {
      id: 'flow-scoping',
      title: 'Scoping',
      blocks: [
        {
          p:
            'PM takes over with "Hand over to scoping". In scoping three things happen, in any ' +
            'order, and the meeting then decides.',
        },
        {
          steps: [
            { title: 'The impacted set', body: 'PM or the lead picks the impacted items on the "Impacted" tab. Development confirms it with "Confirm impact (Development)". Nothing is assessed until it is confirmed.' },
            { title: 'Questions and cancel votes', body: 'Anyone on the team can raise a question for the customer or vote to reject. Sales answers questions; the asker or PM closes them. Open ones block "Proceed".' },
            { title: 'The scoping meeting', body: 'PM records it with the departments and their letters (R, A, S, C) and the cost carrier. The decision is "Proceed & start assessment", "Needs more info" or "Reject".' },
          ],
        },
        {
          callout:
            'Being in the meeting makes nobody responsible, and missing it takes nothing away. The ' +
            'letters decide who assesses.',
        },
      ],
    },
    {
      id: 'flow-assessment',
      title: 'Assessment',
      blocks: [
        {
          p:
            'For a part change five departments assess: Development, Tool Engineer, Manufacturing ' +
            'Engineer, APQP and Packaging Engineer. The room may add others.',
        },
        {
          points: [
            ['The checklist:', 'every row Yes or No. A Yes says what has to be done.'],
            ['Risks:', 'flagged on the row they come from, typed, rated 1 to 3. A risk never blocks the submit.'],
            ['The verdict:', '"Feasible", "Feasible with conditions" or "Not feasible". "Not feasible" needs the change PPT.'],
          ],
        },
        {
          p:
            'When every department on the hook has answered, PM presses "Close assessment → ' +
            'Costing".',
        },
      ],
    },
    {
      id: 'flow-costing',
      title: 'Costing and the quote',
      blocks: [
        {
          p:
            'Each department prices its own part on the "Costing" tab: its own time, estimates or ' +
            'vendor quotes, and a lead time on every line. Rates come from Finance\'s cost sheet. ' +
            'A department sees only its own numbers; PM and Sales see all.',
        },
        {
          p:
            'PM presses "Close costing". Then the "Offer" tab is Sales\'s: rough timing, price, risks, ' +
            'document. Sending offer v1 moves the change to "Quoted". Each sent version is valid 30 ' +
            'days from the customer\'s receipt.',
        },
        {
          p:
            'The customer accepts a sent, unexpired version. With the "PM sign-off" and the ' +
            '"Quality sign-off" from two different people, the change is approved. The release ' +
            'deadline is set at acceptance.',
        },
      ],
    },
    {
      id: 'flow-implementation',
      title: 'Approval, timing and implementation',
      blocks: [
        {
          p:
            'Approved opens the "Timing" tab. The detailed plan starts as a copy of the quote plan. ' +
            'Scheduling decides the bank build. Every responsible team confirms the plan or raises a ' +
            'concern. Then "Validate timing" sets the baseline and Sales publishes the plan to the ' +
            'customer.',
        },
        {
          p:
            'From "Start implementation" on, each department updates progress and actual dates on ' +
            'its own blocks. A date move after the baseline asks for a reason and is listed as a ' +
            'deviation. PM or Sales lock it (accepted internally) or escalate it to the customer.',
        },
        { shot: 'flow-gantt-baseline', alt: 'The detailed plan in tracking mode with baseline ghosts and one slipped block.' },
      ],
    },
    {
      id: 'flow-validation',
      title: 'Validation and release',
      blocks: [
        {
          p:
            'The "Release" tab walks four steps: "Validation checks", "Release checklist", ' +
            '"Lessons learned", "Release & close".',
        },
        {
          points: [
            ['Validation checks:', 'each implementing department passes or fails its own checks.'],
            ['Release checklist:', 'thirteen rows, each owned by a department. "N.a." needs a note.'],
            ['Lessons learned:', 'anyone adds a lesson. PM completes the step, with at least one lesson or a reason why there is none.'],
            ['Release & close:', 'PM releases once nothing blocks, reads the summary (plan against actual, offer against actual) and closes.'],
          ],
        },
      ],
    },
    {
      id: 'flow-issues',
      title: 'Side track: a validation issue',
      blocks: [
        {
          lede: 'A failed check does not just bounce the change back. It becomes an issue with an owner and a route.',
        },
        {
          steps: [
            { title: 'Raise', body: 'On the failed check, "Raise issue". It gets a number (VI-1), a category, a severity and an owner department.' },
            { title: 'Contain', body: 'The owner department records the immediate action. Required first when the severity is "Blocks production".' },
            { title: 'Root cause', body: 'The owner department records why it failed.' },
            { title: 'Route', body: 'PM or the lead decides the route, with a reason. Four eyes: not the person who raised it.' },
            { title: 'Fix and re-check', body: 'The fix actions are ticked, the check is answered again. A pass closes the issue.' },
          ],
        },
        {
          table: {
            head: ['Route', 'What happens'],
            rows: [
              ['"Internal rework"', 'Our own shop fixes it. The change goes back to implementation with a recovery group in the plan.'],
              ['"Supplier rework"', 'The supplier fixes it, optionally at their cost. Same loop back.'],
              ['"Design change"', 'The design itself changes. The customer is told by default.'],
              ['"Customer concession"', 'The customer accepts the part as it is. Closes only when Sales records the decision with the customer\'s mail filed.'],
              ['"Follow-up change"', 'A new change carries the fix. This one can release without it.'],
            ],
          },
        },
        { h3: 'Escalation' },
        {
          table: {
            head: ['Level', 'Who knows'],
            rows: [
              ['"L1 Department"', 'The owner department and PM. Every issue starts here.'],
              ['"L2 Project"', 'PM, the lead and Sales. Automatic on "Blocks production", an overdue fix action, a recovery past the baseline, or no route after two working days.'],
              ['"L3 Management and customer"', 'Management is notified and Sales informs the customer. Automatic when the recovery ends after the release deadline, or an L2 is not acknowledged in two working days.'],
            ],
          },
        },
        { callout: 'No change is released while a validation issue is open.', tone: 'rule' },
        { shot: 'flow-issue-card', alt: 'A validation issue card VI-1 with its stepper, severity chip, "L2" badge and one primary button.' },
      ],
    },
    {
      id: 'flow-mother-plant',
      title: 'Side track: a change from KTX Weissenburg or KTX Solingen',
      blocks: [
        {
          p:
            'Some changes are engineered and sold by the mother plant. We have no feasibility and ' +
            'no quote on them: we inform our team, take their timing and start with bank build ' +
            'planning.',
        },
        {
          steps: [
            { title: 'Start', body: 'The start form offers "Change from" followed by the plant. Their reference, the SOP date and their documents go in. Their MS Project file is optional.' },
            { title: 'Scoping, short', body: 'Development locks the impacted set. PM sends the information to every team that has to act. Each confirms "Read and understood".' },
            { title: 'Straight to timing', body: 'No assessment, costing or offer. The SOP becomes the release deadline. The detailed plan comes from their file, or starts from the SOP milestone.' },
            { title: 'Then as usual', body: 'Team confirmation, "Validate timing", implementation, validation and release. PM informs the mother plant of the baseline instead of a customer publish.' },
          ],
        },
      ],
    },
    {
      id: 'flow-intake',
      title: 'Side track: a new customer index',
      blocks: [
        {
          p:
            'Every new index from the customer, E1 and E2 included, is captured. It stays pending ' +
            'until Development decides how deep it goes. The part shows "Index {rev} pending triage".',
        },
        {
          table: {
            head: ['Route', 'What happens'],
            rows: [
              ['"Full ECR"', 'A new change starts at capture, with the part as the lead item.'],
              ['"Attach to an open change"', 'The index joins a change that is already running on the project.'],
              ['"Engineering review"', 'A light track. The departments serving the part answer "No impact" or "Impact". All "No impact": the index goes live. Any impact: Development escalates to a full ECR.'],
              ['"Administrative"', 'The index goes live now. A reason is required (title block, re-upload, no content change).'],
            ],
          },
        },
        {
          p:
            'Development decides alone. A reason is required for "Administrative" and for any route ' +
            'other than the suggested one.',
        },
      ],
    },
    {
      id: 'flow-rules',
      title: 'Rules that hold everywhere',
      blocks: [
        {
          points: [
            ['A department sees its own numbers.', 'At assessment and costing only PM, Sales, the lead and admins see every department.'],
            ['Two deadlines, one active.', 'The quote deadline until the offer is sent, the release deadline from acceptance on. Both move only with a reason.'],
            ['The plan leads after approval.', 'Bank build, work, sampling, recovery: all hang off the detailed plan.'],
            ['After the baseline, every date move is a deviation.', 'With a reason, visible to everyone.'],
            ['Four eyes where it matters.', 'PM and Quality sign-offs, the route of a validation issue, routing changes, attendance records.'],
          ],
        },
      ],
    },
  ],
}
