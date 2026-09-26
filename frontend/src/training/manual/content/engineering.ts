import type { ContentChapter, PracticeTaskSpec } from './types'

//: Chapter 05, Engineers: Development, Tool Engineer, Manufacturing
//: Engineer, Process Engineer, APQP, Packaging Engineer. eng-assessment,
//: eng-checklist, eng-risks, eng-costing and eng-implementation replace the
//: stubs of the same id in ../chapters.tsx.

export const engineeringChapter: ContentChapter = {
  id: 'engineering',
  number: '05',
  title: 'Engineers',
  summary:
    'Development, Tool Engineer, Manufacturing Engineer, Process Engineer, APQP, Packaging ' +
    'Engineer: assessing, costing, implementing and releasing a change.',
  roles: ['engineering'],
  sections: [
    {
      id: 'eng-role',
      title: 'Your part in a change',
      blocks: [
        {
          lede:
            'You say what the change means for your area, what it costs and how long it takes, ' +
            'then you do the work, prove it holds and tick your part of the release.',
        },
        {
          table: {
            head: ['Stage', 'What you do'],
            rows: [
              ['Scoping', 'Development confirms the impacted set. Everyone else can raise a question or a cancel vote.'],
              ['In Assessment', 'Answer every checklist row, flag risks on the rows, give a verdict.'],
              ['Costing', 'Price your part: your own time, estimates or vendor quotes, a lead time on every line.'],
              ['Timing', 'Confirm the detailed plan for your department, or raise a concern.'],
              ['Implementing', 'Update progress and actual dates on your blocks. Book your time. Report.'],
              ['Validation', 'Pass or fail your checks. Own the validation issues in your area. Tick your release checklist rows.'],
            ],
          },
        },
        {
          p:
            'For a part change all five of Development, Tool Engineer, Manufacturing Engineer, APQP ' +
            'and Packaging Engineer assess. Process Engineer is routed when the scoping meeting ' +
            'gives it a letter.',
        },
      ],
    },
    {
      id: 'eng-assessment',
      title: 'Your assessment',
      blocks: [
        {
          p:
            'Your task appears in "My Tasks" when the scoping meeting proceeds. Open the change, go ' +
            'to "Assessments": you see your own department\'s bucket, open, and one line saying how ' +
            'many departments have submitted. Other departments\' answers are not shared with you.',
        },
        {
          p:
            'The bucket already lists what you assess, taken from the impacted parts: Tool Engineer ' +
            'gets the tools and molds, Manufacturing Engineer the equipment, APQP the gauges, ' +
            'Development the part design.',
        },
        {
          points: [
            ['"Not our responsibility"', 'if it really is not yours. Give the reason and, if you can, who should assess instead. The lead decides.'],
            ['Customer mails', 'are shown in the bucket. The customer communication is Sales\'s, but you may file a mail you received.'],
          ],
        },
        { shot: 'eng-bucket', alt: 'The Tool Engineer bucket on "Assessments" with "To assess" listing the mold, the checklist and the verdict form.' },
      ],
    },
    {
      id: 'eng-checklist',
      title: 'The checklist, row by row',
      blocks: [
        {
          p:
            '"Impacted areas" asks thirteen questions every department answers, plus your own ' +
            'department\'s extras. Every row gets "Yes" or "No". Nothing is pre-selected: an ' +
            'unanswered row and a considered No must not look the same.',
        },
        {
          points: [
            ['"Yes"', 'opens "Remark": what has to be done. That line seeds your costing.'],
            ['"External modification (supplier)"', 'expects an RFQ to the supplier in your bucket. Reported, not enforced.'],
            ['"Rest to No"', 'sets only the rows you have not answered to No. Reviewers see how many came from it ("{n} × No ({b} set via Rest to No)"). Use it for rows you really checked.'],
            ['"+ Own item"', 'adds a row the list does not cover. It counts as Yes.'],
          ],
        },
        {
          table: {
            head: ['Department', 'Extra rows'],
            rows: [
              ['Development', '"Article design update", with the choice "Internal" or "Customer given".'],
              ['APQP', '"PFMEA update", "Control plan update".'],
              ['Packaging Engineer', 'First "Packaging impacted?". No is a complete assessment ("Submit as not impacted"). Yes asks "Layout change", "Change packaging type", "Modify packaging".'],
            ],
          },
        },
        { shot: 'eng-checklist', alt: '"Impacted areas" with "8 of 13 answered", one Yes row with its remark, and "Rest to No".' },
      ],
    },
    {
      id: 'eng-risks',
      title: 'Flagging a risk on a row',
      blocks: [
        {
          p:
            'If a Yes row worries you, press "⚑ Flag risk" on it. Pick the risk type, rate it 1 to 3 ' +
            '(3 = highest risk) and describe it. The row then lists its open risks and jumps to ' +
            'the risk card. Only a Yes row carries the button: a worry about a No row goes in with ' +
            '"+ Risk not on the checklist".',
        },
        {
          points: [
            ['Risks never block your submit.', 'You submit your verdict with your open risks.'],
            ['Severity 3 is flagged to Sales.', 'Every risk starts hidden on the offer. Sales decides whether the customer reads it or it is priced, and the offer warns while a severity-3 risk is hidden.'],
            ['A risk on no row, or on a No row:', '"+ Risk not on the checklist" in the risk panel.'],
            ['Raised by mistake:', '"Delete (added by mistake)", only yours, only while nothing hangs off it. Otherwise close it as resolved.'],
          ],
        },
        { h3: 'The verdict' },
        {
          table: {
            head: ['Verdict', 'When'],
            rows: [
              ['"Feasible"', 'You can do it as asked.'],
              ['"Feasible with conditions"', 'You can, if something holds. Write the conditions.'],
              ['"Not feasible"', 'You cannot. The change PPT in your bucket is required: it is the explanation.'],
            ],
          },
        },
        {
          p:
            '"Submit assessment" asks you to confirm: once submitted the answer is read only, and ' +
            'changing it needs the Project Manager.',
        },
        { shot: 'eng-risk-on-row', alt: 'A checklist row with "⚑ Flag risk" open: risk type, the rating from 1 to 3 and the description.' },
      ],
    },
    {
      id: 'eng-costing',
      title: 'Your costing input',
      blocks: [
        {
          p:
            'At costing your "Cost positions" table opens with standing rows: "Assessment effort" ' +
            'and "Implementation support". Tool Engineer has a third, "Part weight", an estimate ' +
            'validated later. Your Yes rows from the checklist are already there.',
        },
        {
          table: {
            head: ['Line type', 'Use it for'],
            rows: [
              ['"Own time"', 'Hours your department spends. Priced at the rate from Finance\'s cost sheet.'],
              ['"External · estimate"', 'A number you have without a quote. Name who gave it if you can.'],
              ['"External · vendor quote"', 'Supplier offers under the line: "+ offer" per vendor with price, shipping, lead time and the quote document.'],
              ['Machine time, sampling', 'Hours at the machine class rate, or trials at the sampling price.'],
            ],
          },
        },
        {
          points: [
            ['A lead time on every line.', 'The quote plan is built from them. A line without a lead time is a plan without a date.'],
            ['The star is your recommendation.', 'One favorite per position. Sales decides and is accountable; a different choice is recorded with a reason.'],
            ['Full or partial quote.', 'Full quotes are alternatives; one is bought. A partial quote is part of the line and always counted.'],
            ['"No rate in the cost sheet"', 'on a line means it is not counted. Tell Finance; they add the rate.'],
          ],
        },
        { shot: 'eng-cost-positions', alt: 'The "Cost positions" table with the standing rows and one "External · vendor quote" line with two offers, one starred.' },
      ],
    },
    {
      id: 'eng-plan',
      title: 'Confirming the plan',
      blocks: [
        {
          p:
            'When the change is approved, the detailed plan appears on "Timing". Your department is ' +
            'asked on the "Team confirmation" panel: "Confirm timing", or "Raise concern" with what ' +
            'does not work and what would.',
        },
        {
          callout:
            'A confirmation is a promise that your blocks can be done in the time shown. If the plan ' +
            'changes afterwards, your confirmation is marked "Plan changed after this confirmation" ' +
            'and you are asked again.',
        },
        { shot: 'eng-team-confirmation', alt: 'The "Team confirmation" panel with the department row, "Confirm timing" and "Raise concern".' },
      ],
    },
    {
      id: 'eng-implementation',
      title: 'Implementation',
      blocks: [
        {
          points: [
            ['Progress on your blocks:', 'open a block in the plan and set "Progress", "Actual start", "Actual finish". Members of the block\'s owner department may; everything else is read only.'],
            ['Booked time:', 'under "Reports and time booking", "Hours" and "What for?", then "Book time". Actual cost is booked hours times the rate.'],
            ['Progress reports:', '"What happened?", and "This is at risk" with what is at risk. The chip says when a report is due.'],
            ['A date that will not hold:', 'tell PM. After the baseline only PM, Sales, Scheduling and the lead move dates, and each move is a deviation with a reason.'],
          ],
        },
        { shot: 'eng-tracker', alt: '"Reports and time booking" for one department with "report due", booked hours and the report form.' },
      ],
    },
    {
      id: 'eng-validation',
      title: 'Validation checks and issues',
      blocks: [
        {
          p:
            'In validation your department answers its own checks on the "Release" tab, for ' +
            'example "Tool sampled", "Part measured", "Measured cycle time", "Part weight ' +
            'validated", "Packaging validated with the changed part". "Pass", or "Fail" with what ' +
            'is not in order. A fail without a reason is not a check. "Measured cycle time" and ' +
            '"Part weight validated" pass only with the measured value entered.',
        },
        {
          p:
            'On a failed check press "Raise issue". The issue gets an owner department: the one ' +
            'that fixes it. As the owner you act in this order.',
        },
        {
          steps: [
            { title: '"Record containment"', body: 'Immediate action: hold parts, protect the bank, run the old state. Required first when the severity is "Blocks production".' },
            { title: '"Record root cause"', body: 'Why it failed, measured and confirmed.' },
            { title: 'Wait for the route', body: 'PM or the lead decides it, with the fix actions.' },
            { title: '"Tick my fix action"', body: 'When your action is done. When all are done the issue waits for the re-check.' },
            { title: 'Answer the check again', body: 'A pass closes the issue. A fail sends it back to fixing.' },
          ],
        },
        {
          p:
            'An escalation to L2 or L3 asks the people told to "Acknowledge". Unacknowledged for ' +
            'two working days, L2 rises to L3 on its own.',
        },
        { shot: 'eng-failed-check', alt: 'A failed validation check with its reason and the "Raise issue" button.' },
      ],
    },
    {
      id: 'eng-release',
      title: 'Your release checklist rows',
      blocks: [
        {
          p:
            'Each row of the release checklist is owned by one department. Mark it "Done", or ' +
            '"N.a." with a note that says why it does not apply. The Process Engineer keeps the ' +
            'process details (parameters, PFMEA, work instructions) in the process database (PDB) ' +
            'and confirms them there; the release asks only the cycle time and process stability.',
        },
        {
          table: {
            head: ['Department', 'Rows'],
            rows: [
              ['Development', '"Part index / revision level updated in drawing and PLM", "Drawing and 3D data released and distributed", "Spare and service parts considered".'],
              ['Tool Engineer', '"Tool and equipment data updated (tool card, equipment list)", "Part weight measured and recorded".'],
              ['Process Engineer', '"Cycle time: changed (new value entered) or confirmed unchanged": pick "Changed" and enter the new seconds, or "Unchanged". "Process stable: SPC Cm > 1.67 (Process Engineer)", Cm optional.'],
              ['APQP', '"Process stable: SPC Cm > 1.67 (APQP)", "Surface quality confirmed", "Technical quality confirmed", "Measurements confirmed, measurement report on file", "PPAP / initial sample documentation complete, customer approval received (ISIR / PSW)", "Control plan / inspection plan updated".'],
              ['Packaging Engineer', '"Packaging instruction updated".'],
            ],
          },
        },
        { callout: 'Process stability is one confirmation owed by two departments: it counts only when the Process Engineer row and the APQP row are both "Done". Each row shows where the other half stands.', tone: 'rule' },
        { shot: 'eng-release-checklist', alt: 'The release checklist grouped by department with "Done" and "N.a." chips and one note.' },
      ],
    },
    {
      id: 'eng-development',
      title: 'Development only: the impacted set and new indexes',
      blocks: [
        { h3: 'Confirming the impacted set' },
        {
          p:
            'At scoping PM builds the impacted set. You check it and press "Confirm impact ' +
            '(Development)". Only Development can. The assessment is routed on this set, and any ' +
            'later edit clears your confirmation.',
        },
        { h3: 'Triage of a new customer index' },
        {
          p:
            'Every new index from the customer lands in "My Tasks" under "New indexes": "Triage ' +
            'index {rev} of {part}". The index stays pending until you decide. You decide alone.',
        },
        {
          table: {
            head: ['Route', 'Pick it when'],
            rows: [
              ['"Full ECR"', 'The index changes the part in a way that needs the full process. Suggested for official data and for every index on a series part.'],
              ['"Attach to an open change"', 'A change in the same project is already running, not yet past implementation, and this index belongs to it.'],
              ['"Engineering review"', 'Probably no impact, but the serving departments should say so. Suggested for E-level (review) data on a part not yet in series.'],
              ['"Administrative"', 'Nothing changes in content: title block, a re-upload. The index goes live now ("Activate now"). Suggested for the very first data on an RFQ part.'],
            ],
          },
        },
        {
          p:
            'A reason is required for "Administrative" and whenever you pick another route than the ' +
            'suggested one.',
        },
        { h3: 'Engineering review' },
        {
          p:
            'On the review, "Lock the impact" takes you to "Impacted", where you lock the set with ' +
            '"Confirm impact (Development)". The departments serving the part then answer "No ' +
            'impact", or "Impact" with a note (the note is required only for "Impact"). All "No ' +
            'impact": the index goes live and the review closes. Any impact: "Escalate to a full ' +
            'ECR".',
        },
        { shot: 'eng-intake-route', alt: 'The "Triage index C of 20-9001-001-0" dialog with the four routes and the "Suggested:" chip.' },
      ],
    },
    {
      id: 'eng-mistakes',
      title: 'Common mistakes',
      blocks: [
        {
          points: [
            ['A Yes without a remark.', 'It cannot be costed or planned. Say what has to be done.'],
            ['"Rest to No" to get the list done.', 'Reviewers see how many rows it set. Look at the rows first.'],
            ['A costing line without a lead time.', 'The quote plan has no date for your work and the customer gets a wrong timing.'],
            ['Confirming a plan you did not read.', 'Your confirmation is what "Validate timing" relies on.'],
            ['A failed check without a reason.', 'The owner of the fix cannot start.'],
            ['Development: "Administrative" for a real change.', 'The index goes live with nobody assessing it.'],
          ],
        },
      ],
    },
  ],
}

export const engineeringTasks: PracticeTaskSpec[] = [
  {
    key: 'eng_answer_checklist_row',
    role: 'engineering',
    title: 'Answer a checklist row',
    status: 'ready',
    screen: { kind: 'assessment', department: 'Tool Engineer' },
    brief:
      'CR-TRAIN-0002 is waiting for the Tool Engineer assessment. The reinforced clip tower ' +
      'means the mold is modified in house. Answer the row "Internal modification" and say ' +
      'what has to be done.',
    why:
      'Every row is answered Yes or No, and a Yes carries the work behind it. That line is what ' +
      'costing prices and what the plan schedules.',
    fixture: ['CR-TRAIN-0002 in assessment with a Tool Engineer row (exists today).'],
    pass: [
      { assert: 'the draft or submission answers modification_internal yes', hint: 'The row "Internal modification" is unanswered or No.' },
      { assert: 'its remark has at least 5 characters', hint: 'The row says Yes but not what has to be done.' },
    ],
  },
  {
    key: 'eng_submit_assessment',
    role: 'engineering',
    title: 'Submit the assessment',
    status: 'ready',
    screen: { kind: 'assessment', department: 'Tool Engineer' },
    brief:
      'Finish the Tool Engineer assessment on CR-TRAIN-0002: the internal modification is ' +
      'needed (say what), nothing else on the list is affected. The change is feasible. ' +
      'Submit it.',
    why:
      'A department that has not submitted holds the whole change in assessment. "Rest to No" ' +
      'answers the untouched rows in one step, and reviewers can see it was used.',
    fixture: ['CR-TRAIN-0002 in assessment (exists today).'],
    pass: [
      { assert: 'a Tool Engineer submission exists with a feasible verdict', hint: 'The assessment has not been submitted, or the verdict is not feasible.' },
      { assert: 'modification_internal is yes with a remark', hint: '"Internal modification" should be Yes, with what has to be done.' },
      { assert: 'no other row is yes', hint: 'More rows say Yes than the brief describes.' },
    ],
  },
  {
    key: 'eng_costing_vendor_quotes',
    role: 'engineering',
    title: 'Price a line with two vendor quotes',
    status: 'needs-sandbox',
    screen: { kind: 'costing', change: 'CR-TRAIN-0006', department: 'Tool Engineer' },
    brief:
      'The insert for CR-TRAIN-0006 is made outside. Toolmaker A quotes 18,500 in 35 days, ' +
      'shipping included. Toolmaker B quotes 16,900 in 49 days plus 400 shipping. The ' +
      'customer\'s timing is tight, so you recommend A. Enter the line with both quotes and ' +
      'their documents.',
    why:
      'Sales chooses the vendor, but from your line: both prices, both lead times, your ' +
      'recommendation. The lead time is what the quote plan is built from.',
    fixture: [
      'CR-TRAIN-0006 in costing, Tool Engineer costing input open, a tool change category available.',
      'Trainee acts as a Tool Engineer member.',
      'Two sample PDF files to upload as quote documents.',
    ],
    pass: [
      { assert: 'a Tool Engineer position with pricing quote exists', hint: 'There is no "External · vendor quote" line yet.' },
      { assert: 'it has two full (not partial) offers with price and lead time', hint: 'Both toolmakers belong on the line as alternatives, each with its price and lead time.' },
      { assert: 'offer B has shipping 400 separate, offer A shipping included', hint: 'Check the shipping of each offer.' },
      { assert: 'the favorite is offer A', hint: 'Star toolmaker A: it is your recommendation because of the tight timing.' },
      { assert: 'each offer carries a quote document', hint: 'A quote without its document cannot be checked. Attach both.' },
    ],
  },
  {
    key: 'eng_contain_issue',
    role: 'engineering',
    title: 'Contain an issue and record its cause',
    status: 'needs-sandbox',
    screen: { kind: 'validation-issue', change: 'CR-TRAIN-0009' },
    brief:
      'VI-1 on CR-TRAIN-0009 is yours as Tool Engineer: the clip tower breaks at the first ' +
      'sampling, and production is blocked. You have put the new parts on hold and the line ' +
      'runs the old state from the bank. The cause is a sharp corner in the new insert, ' +
      'confirmed by the section cut. Record both.',
    why:
      'At "Blocks production" nothing can be decided until the parts are contained, and no ' +
      'fix route is decided without a cause. Recorded, they are the start of the fix.',
    fixture: [
      'CR-TRAIN-0009 in_validation, VI-1 severity 3, owner Tool Engineer, raised by another user, not contained.',
      'Trainee acts as a Tool Engineer member.',
    ],
    pass: [
      { assert: 'VI-1 containment has at least 15 characters', hint: 'The containment is not recorded yet. Say what was held and how the line runs.' },
      { assert: 'VI-1 root_cause has at least 15 characters', hint: 'The root cause is not recorded yet.' },
    ],
  },
]
