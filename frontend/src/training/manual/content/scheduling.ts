import type { ContentChapter, PracticeTaskSpec } from './types'

//: Chapter 06, Scheduling. Section ids sch-assessment, sch-bankbuild and
//: sch-plan replace the stubs of the same id in ../chapters.tsx.

export const schedulingChapter: ContentChapter = {
  id: 'scheduling',
  number: '06',
  title: 'Scheduling',
  summary: 'How the change reaches the line: bank build or running change, the plan, stock and ERP.',
  roles: ['scheduling'],
  sections: [
    {
      id: 'sch-role',
      title: 'Your part in a change',
      blocks: [
        {
          lede:
            'You decide how a change reaches the line without the customer running short. ' +
            'You help build the plan, you confirm it, and at the end you make sure ERP and ' +
            'the old stock are in order.',
        },
        {
          table: {
            head: ['Stage', 'What you do'],
            rows: [
              ['Assessment', 'Only if the scoping meeting routed you. Then you answer the checklist like every department.'],
              ['Costing to quoted', 'You may edit the quote plan with PM and Sales.'],
              ['Approved', 'You decide the bank build plan, refine the detailed plan and confirm the timing.'],
              ['In implementation', 'You report progress on your own blocks. A date move needs a reason.'],
              ['In validation', 'You tick "ERP, BOM and routing updated" and "Old stock handled as agreed (bank consumed or scrapped)".'],
            ],
          },
        },
        {
          callout:
            'For a normal part change Scheduling has no assessment task. The five engineering ' +
            'departments assess. You come in at the plan, where you are always asked to confirm.',
        },
      ],
    },
    {
      id: 'sch-assessment',
      title: 'Your assessment, when you are routed',
      blocks: [
        {
          p:
            'Sometimes the scoping meeting gives Scheduling a letter R or A, for example ' +
            'when a cycle time change eats press capacity. Then an assessment task appears in ' +
            '"My Tasks" and your bucket opens on the "Assessments" tab.',
        },
        {
          points: [
            ['Every row gets Yes or No.', 'A Yes says what has to be done. That text becomes your costing line.'],
            ['"Cycle time change" is yours to judge.', 'A longer cycle is lost press capacity. Say how many shots and which press.'],
            ['"Rest to No"', 'fills only the rows you have not answered. Use it after you looked at them, not instead.'],
          ],
        },
        { shot: 'sch-assessment-checklist', alt: 'The Scheduling bucket on the Assessments tab with "Cycle time change" answered Yes and a remark.' },
      ],
    },
    {
      id: 'sch-bankbuild',
      title: 'Bank build or running change',
      blocks: [
        {
          lede:
            'A tool that goes to the shop cannot make parts. Before it leaves, either a bank of ' +
            'parts is built, or the change runs in without a stop.',
        },
        {
          p:
            'On the "Timing" tab the "Bank build plan" card asks: "How does the change reach ' +
            'the line?" There are two modes. Often the accepted offer has already set it: when ' +
            'nobody decided yet, acceptance takes the offer\'s changeover, "Running change", or ' +
            '"Customer pays scrap" as "Planned scrap" at the offered scrap quantity times the unit ' +
            'price. Check what the card shows and correct it while the change is approved.',
        },
        {
          table: {
            head: ['Mode', 'What it means'],
            rows: [
              ['"Running change"', 'Switch over in running production. No scrap planned.'],
              ['"Planned scrap"', 'Remaining stock is scrapped and the bank is rebuilt. Needs a "Scrap quote price": the total the customer pays for the scrapped stock, as an additional quote.'],
            ],
          },
        },
        {
          p:
            'Write the cut-over date, the coverage and the plants in the "Plan note". Then press ' +
            '"Save". Only Scheduling, PM, the change lead or an admin can set the plan.',
        },
        { shot: 'sch-bank-build-card', alt: 'The "Bank build plan" card with "Planned scrap" selected, a scrap quote price and a plan note.' },
        { h3: 'The bank build block in the plan' },
        {
          p:
            'When the quote plan has a tool downtime, it adds a "Bank build (idea)" block on its ' +
            'own: a dashed bar that ends where the first tool downtime starts. Sales may move or ' +
            'redraw it. An idea is a proposal. It does not push committed work and is not on the ' +
            'critical path.',
        },
        {
          steps: [
            { title: 'Make it real or delete it', body: 'Open the block (double-click), untick "Idea block", set its real length and owner. Or delete it if there is no bank build.' },
            { title: 'Check it ends before the downtime', body: 'The plan warns when a bank build ends after the first downtime starts. A bank that is still being built while the tool is away is no bank.' },
            { title: 'No idea block survives validation', body: '"Validate timing" stays disabled while the detailed plan still holds an idea block.' },
          ],
        },
        { shot: 'sch-bank-build-idea', alt: 'The Gantt with a dashed "Bank build (idea)" bar ending at the start of a "Tool downtime" bar.' },
      ],
    },
    {
      id: 'sch-plan',
      title: 'The plan',
      blocks: [
        {
          p:
            'The plan is a Gantt, close to MS Project. PM, Sales, Scheduling and the change lead ' +
            'edit it. Everyone else sees it and reports progress on their own blocks.',
        },
        {
          points: [
            ['Quote plan', 'is the rough timing Sales shows the customer. Editable from costing until the change is approved.'],
            ['Detailed plan', 'starts as a copy of the quote plan when the change is approved: "Create detailed plan from quote plan". You refine it with the teams.'],
            ['Team confirmation', 'Every responsible team, Scheduling included, answers "Confirm timing" or "Raise concern".'],
            ['"Validate timing"', 'sets the baseline. PM, Scheduling or Sales press it once every team has confirmed.'],
          ],
        },
        {
          callout:
            'Any edit to the detailed plan before validation makes every confirmation stale. The chip ' +
            'then reads "Plan changed after this confirmation". Confirm again after the last edit.',
          tone: 'warn',
        },
        { shot: 'sch-team-confirmation', alt: 'The "Team confirmation" panel with "Confirm timing" and "Raise concern" for Scheduling and one stale chip.' },
        { h3: 'After the baseline: every date move is a deviation' },
        {
          p:
            'Once the timing is validated, moving a block opens "Record a deviation" and asks "Why ' +
            'does this move?". The move is saved with your reason and listed under "Deviations from ' +
            'the baseline", with the blocks it pushed along under it as one group. PM, Sales or the ' +
            'lead then decide the group once: lock it or escalate it to the customer.',
        },
        { shot: 'sch-deviation-dialog', alt: 'The "Record a deviation" dialog with a reason typed and "Save move".' },
        { h3: 'Changes from KTX Weissenburg or KTX Solingen' },
        {
          p:
            'Project Management starts a change engineered by the mother plant. It has no ' +
            'assessment and no offer. Scoping only records which departments are informed; PM ' +
            'sends the information and each informed department confirms "Read and understood". ' +
            'Then it is approved, with the mother plant\'s SOP as the release deadline. Your bank ' +
            'build planning is the first real work on it. Their MS Project file, if they sent one ' +
            'at the start, seeds the detailed plan at approval. A later file is loaded with ' +
            '"Import MS Project".',
        },
      ],
    },
    {
      id: 'sch-release',
      title: 'Release: ERP and old stock',
      blocks: [
        {
          p:
            'In validation the "Release" tab lists the release checklist. Two rows are Scheduling\'s. ' +
            'Tick "Done", or "N.a." with a note that says why it does not apply.',
        },
        {
          points: [
            ['"ERP, BOM and routing updated"', 'The new index, the BOM and the routing are live in ERP.'],
            ['"Old stock handled as agreed (bank consumed or scrapped)"', 'What the bank build or scrap plan promised has happened.'],
          ],
        },
        { shot: 'sch-release-checklist', alt: 'The release checklist grouped by department with the two Scheduling rows marked "Done".' },
      ],
    },
    {
      id: 'sch-mistakes',
      title: 'Common mistakes',
      blocks: [
        {
          points: [
            ['Leaving an idea block in the detailed plan.', 'Timing cannot be validated until it is real or gone.'],
            ['A bank build that ends after the downtime starts.', 'The plan warns. Move the bank earlier or make it longer.'],
            ['Confirming, then editing.', 'Your own edit makes your confirmation stale too.'],
            ['"Planned scrap" without a price.', 'The card refuses it: "Planned scrap needs a scrap quote price".'],
            ['A reason like "update".', 'The reason is read by the customer if the move is escalated. Say what happened.'],
          ],
        },
      ],
    },
  ],
}

export const schedulingTasks: PracticeTaskSpec[] = [
  {
    key: 'sch_bank_build_plan',
    role: 'scheduling',
    title: 'Decide the bank build plan',
    status: 'needs-sandbox',
    replaces: 'sch_answer_checklist_row',
    screen: { kind: 'timing', change: 'CR-TRAIN-0003' },
    brief:
      'CR-TRAIN-0003 is approved. The mold goes to the toolmaker for three weeks and the ' +
      'customer will not take a supply gap. Old parts at the old index cannot be sold after ' +
      'the change. Set the bank build plan: the remaining stock is scrapped, and the scrap ' +
      'quote to the customer is 4,800.00 (2,000 parts at 2.40). The note says when the bank ' +
      'is built.',
    why:
      'The bank build mode decides whether the customer pays scrap and what the offer and ' +
      'the plan must carry. Undecided, the plan cannot go to the customer.',
    fixture: [
      'CR-TRAIN-0003, customer change, status approved, no bank-build mode set: the accepted offer carried no changeover decision to take over ("Customer pays scrap" without a scrap price).',
      'Detailed plan seeded with a "Tool downtime" block of 21 days.',
      'Trainee acts as a Scheduling member.',
    ],
    pass: [
      { assert: 'change.bank_build_mode is planned_scrap', hint: 'The mode is still not "Planned scrap". Old stock is scrapped here.' },
      { assert: 'change.scrap_quote_price is 4800.00', hint: 'The "Scrap quote price" is the total the customer pays for the scrapped stock: 2,000 parts at 2.40.' },
      { assert: 'the plan note has at least 10 characters', hint: 'The plan note is empty or too short. Say when the bank is built and how long it covers.' },
    ],
  },
  {
    key: 'sch_resolve_bank_idea',
    role: 'scheduling',
    title: 'Turn the bank build idea into a real block',
    status: 'needs-sandbox',
    screen: { kind: 'timing', change: 'CR-TRAIN-0016' },
    brief:
      'The detailed plan of CR-TRAIN-0016 still holds the "Bank build (idea)". The bank really is built, ' +
      'by Scheduling, in the ten days before the tool leaves. Make the idea a real block ' +
      'that ends no later than the tool downtime starts.',
    why:
      'An idea block stops "Validate timing". A bank that ends after the downtime starts ' +
      'is a supply gap.',
    fixture: [
      'CR-TRAIN-0016 approved, detailed plan with a "Tool downtime" block and a "Bank build (idea)" block that ends 3 days after the downtime starts.',
      'No baseline yet.',
      'Trainee acts as a Scheduling member.',
    ],
    pass: [
      { assert: 'no block in the detailed plan has is_idea true', hint: 'The plan still has an idea block. Untick "Idea block" or delete the idea.' },
      { assert: 'a block of kind bank_build exists', hint: 'There is no bank build block left. The bank is really built, so keep one.' },
      { assert: 'that block ends on or before the first downtime start', hint: 'The bank build still ends after the tool leaves. Move it earlier or shorten it.' },
    ],
  },
  {
    key: 'sch_timing_concern',
    role: 'scheduling',
    title: 'Raise a concern about the timing',
    status: 'needs-sandbox',
    screen: { kind: 'timing', change: 'CR-TRAIN-0017' },
    brief:
      'The detailed plan of CR-TRAIN-0017 puts the tool downtime in the plant shutdown week, when no bank can ' +
      'be shipped. Do not confirm the timing. Tell the team what does not work and what would.',
    why:
      'A confirmation is a promise. A concern with a reason is what lets PM fix the plan ' +
      'before the baseline is set, when it is still free to change.',
    fixture: [
      'CR-TRAIN-0017 approved, detailed plan at plan_revision 2, no Scheduling feedback yet.',
      'Trainee acts as a Scheduling member.',
    ],
    pass: [
      { assert: 'the latest Scheduling feedback is verdict concern at the current plan revision', hint: 'Scheduling has not raised a concern on this plan yet.' },
      { assert: 'the concern note has at least 15 characters', hint: 'The concern needs a note that says what does not work and what would.' },
    ],
  },
  {
    key: 'sch_release_stock',
    role: 'scheduling',
    title: 'Tick your release checklist rows',
    status: 'needs-sandbox',
    screen: { kind: 'release', change: 'CR-TRAIN-0011' },
    brief:
      'CR-TRAIN-0011 is in validation. The new routing is live in ERP. The bank was consumed ' +
      'as planned. Answer both Scheduling rows of the release checklist.',
    why:
      'Release waits for every row. An old part left in stock at the old index is shipped by ' +
      'somebody who did not know.',
    fixture: [
      'CR-TRAIN-0011 in_validation, release checks seeded, all open.',
      'Trainee acts as a Scheduling member.',
    ],
    pass: [
      { assert: 'check erp_updated has status done', hint: '"ERP, BOM and routing updated" is still open.' },
      { assert: 'check stock_handled has status done', hint: '"Old stock handled as agreed (bank consumed or scrapped)" is still open.' },
      { assert: 'no other department\'s check was changed', hint: 'Only the two Scheduling rows were to be answered.' },
    ],
  },
]
