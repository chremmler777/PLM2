import type { ContentChapter, PracticeTaskSpec } from './types'

//: Chapter 04, Sales. sales-start, sales-documents and sales-quote replace
//: the stubs of the same id in ../chapters.tsx.

export const salesChapter: ContentChapter = {
  id: 'sales',
  number: '04',
  title: 'Sales',
  summary: 'Starting a change request, the offer, negotiation, the customer\'s answer, and every customer contact after it.',
  roles: ['sales'],
  sections: [
    {
      id: 'sales-role',
      title: 'Your part in a change',
      blocks: [
        {
          lede:
            'You own the customer. You start the request, you build and send the offer, you log ' +
            'every round, and anything the customer has to hear after acceptance goes through you.',
        },
        {
          table: {
            head: ['Stage', 'What you do'],
            rows: [
              ['Captured', 'Start the request with its reason, parts, documents and quote deadline.'],
              ['Scoping', 'Answer the team\'s questions for the customer. Send the rejection letter if the change is rejected.'],
              ['Costing', 'Nothing to enter. You see every department\'s numbers and may start the rough timing.'],
              ['Quote creation', 'Build the offer: timing, price, risks, document. Send v1.'],
              ['Quoted', 'Log each round, send new versions, record the customer\'s answer.'],
              ['Timing', 'Confirm the plan for Sales, publish the validated plan to the customer.'],
              ['Implementing', 'Tell the customer about escalated deviations.'],
              ['Validation', 'Record the customer\'s decision on a validation issue, quote a fix the customer pays, tick "Customer informed of the implementation date / first shipment".'],
            ],
          },
        },
      ],
    },
    {
      id: 'sales-start',
      title: 'Starting a change request',
      blocks: [
        {
          p:
            '"New Change Request" on the "Changes" page, or "Start change request" on the part ' +
            'itself. The form is "New change request".',
        },
        {
          steps: [
            { title: 'Project and affected items', body: 'Pick every part that changes with the same tool, for example the PEAK variant from the same mold. The first one is the lead item; "Make lead item" changes it.' },
            { title: 'Short description', body: 'One line: what is the problem. It is capped at 100 characters. The detail goes in the documents.' },
            { title: 'Who carries the cost', body: '"Customer change" when the customer pays. It goes through the quote workflow.' },
            { title: 'Quote deadline', body: 'When the customer expects the offer. Optional on the form. The hand-over to scoping asks for it, and for a change lead; without them the hand-over needs an approved deviation.' },
            { title: 'Customer documents', body: 'Drop the drawing, the mail, the specification. At least one is required before scoping.' },
            { title: 'Create change', body: 'The form tells you if it is "Ready to hand over to scoping" or what is missing.' },
          ],
        },
        {
          callout:
            'One request per tool family. Two requests for parts from the same tool means two ' +
            'assessments, two offers and two revisions for one piece of work.',
          tone: 'warn',
        },
        { shot: 'sales-start-form', alt: 'The "New change request" form with two affected items, the lead marked, a short description and the quote deadline.' },
      ],
    },
    {
      id: 'sales-documents',
      title: 'The customer\'s documents and questions',
      blocks: [
        {
          points: [
            ['Customer mails', 'are filed on the change as a tracked list. Everybody may upload one; you own the relationship.'],
            ['A question from the team', 'arrives as an open question at scoping. "Sales answers this question." Answer it and drop the customer\'s reply. The asker or PM then marks it solved; you never do.'],
            ['"Needs more info"', 'from the scoping meeting gives you the task to get the missing information from the customer.'],
            ['A rejected change', 'shows "Send rejection letter": attach the letter, send it, then "Sent to customer, close ECR".'],
          ],
        },
        { shot: 'sales-question-card', alt: 'An open question card with "Asked by", the Sales answer box and "Drop the customer\'s answer here".' },
      ],
    },
    {
      id: 'sales-quote',
      title: 'Building the offer',
      blocks: [
        {
          p:
            'When PM closes costing, the "Offer" tab is yours. "Start the offer" pre-fills it from ' +
            'costing: one cost line per department and external position, the standard factors ' +
            '(off), the open risks, the changeover mode and the rough timing from the quote plan.',
        },
        {
          table: {
            head: ['Step', 'What you decide'],
            rows: [
              ['"Timing"', 'The rough plan. Move blocks, run work in parallel, add a bank build idea and a safety buffer. "Include in offer" and the weeks from order.'],
              ['"Price"', 'The cost lines, factors (overhead, margin, fees, discount), the changeover ("Running change" or "Customer pays scrap"), the piece-price effect, additional items.'],
              ['"Risks"', 'Which risks the customer reads, and a surcharge where a risk is real money.'],
              ['"Document"', 'Recipient, subject, the scope as the customer reads it, "Detailed cost breakdown (CBD)" or "Rough description", terms.'],
            ],
          },
        },
        { shot: 'sales-offer-price', alt: 'The "Price" step with cost lines from costing, the factors with "Show on offer" and the "Offer sum" card.' },
        {
          points: [
            ['Vendor choice:', 'the department\'s star is a recommendation. Your choice in the "Vendor decision" is binding and recorded; against the recommendation you give a reason.'],
            ['Risks start hidden:', 'no risk is on the offer until you switch it on. The page warns while a severity-3 risk is not shown. State it, or price it, knowingly.'],
            ['"Result vs internal cost"', 'shows the margin before you send. The totals are computed by the server; what you see is what goes out.'],
            ['"↻ Refresh from costing"', 'pulls the current costing into the draft, keeping your own lines and overrides.'],
          ],
        },
        { h3: 'The document' },
        {
          p:
            'The PDF carries the KTX Group US Corp. letterhead of the Toccoa site, the offer number ' +
            '(change number, Q, version), the scope, the price, changeover, timing with a draft ' +
            'disclaimer, the risks you chose and the terms. The validity is fixed: 30 days from the ' +
            'customer\'s receipt. "Preview PDF" shows the draft with a DRAFT watermark.',
        },
        {
          p:
            'Sales signs the offer. The version you send carries your name and "Sales" under the ' +
            'letterhead, and keeps it for good. A draft preview shows the project\'s Sales ' +
            'responsible, or you when nobody is set.',
        },
        { shot: 'sales-offer-pdf', alt: 'Page 1 of an offer PDF: letterhead, "OFFER" with number and valid-until date, recipient and "1. Scope of change".' },
        { h3: 'Sending' },
        {
          p:
            '"Send offer" asks when the customer received it ("Received by the customer on"). The ' +
            'offer is valid 30 days from that date. Sending v1 sets the quoted price and moves the ' +
            'change to "Quoted".',
        },
      ],
    },
    {
      id: 'sales-versions',
      title: 'Negotiation and new versions',
      blocks: [
        {
          points: [
            ['Log every round:', '"+ Record round" under "Negotiation" with the channel ("Meeting", "Call", "Email"), what came out of it and any counter price.'],
            ['A new price is a new version:', '"New version" clones the last sent one. Change it, then send.'],
            ['What changed:', 'from v2 on, sending asks "What changed against the last version? (internal, not printed; required)". The page also shows the before and after of every changed figure.'],
            ['Validity:', 'the header shows how many days are left. An expired offer can only be accepted with an "Override reason".'],
          ],
        },
        { shot: 'sales-offer-versions', alt: 'The "Negotiation" timeline with offer v1 superseded, one round, and v2 sent with "What changed:" and "valid until".' },
      ],
    },
    {
      id: 'sales-answer',
      title: 'The customer\'s answer',
      blocks: [
        {
          steps: [
            { title: '"Customer accepted"', body: 'Enter the "Release deadline" the customer agreed and "Confirm acceptance". The release deadline starts here.' },
            { title: 'Or "Customer declined"', body: 'This cannot be undone. The offer is closed and the change cannot be approved on it.' },
            { title: 'Sign-offs', body: 'PM and Quality then give their sign-offs. Approval needs all three.' },
          ],
        },
        { shot: 'sales-customer-response', alt: 'The "Customer response" block on v2 with "Customer accepted", "Customer declined" and the sign-off buttons below.' },
      ],
    },
    {
      id: 'sales-after',
      title: 'After acceptance: the plan, deviations, issues',
      blocks: [
        {
          points: [
            ['Confirm the plan.', 'Sales is always asked on the "Team confirmation" panel.'],
            ['"Publish plan to customer"', 'once the timing is validated and the bank build mode is set. It records that you sent the validated timing; export it with "MS Project" or "CSV" to attach.'],
            ['Escalated deviations', 'are yours to tell the customer. The escalation says what Sales tells them.'],
            ['Validation issue, customer to be informed:', '"Record customer decision": "Accepts the deviation", "Requires a fix", "New timing" or "Pending". A concession only closes with the customer\'s mail filed into the issue.'],
            ['A fix the customer pays:', 'you get the task to quote it. "Quote the fix", then "Fix quoted to the customer".'],
            ['Release:', 'tick "Customer informed of the implementation date / first shipment".'],
          ],
        },
        { shot: 'sales-issue-decision', alt: 'The customer decision form on a validation issue with "Accepts the deviation" selected and a customer mail filed.' },
      ],
    },
    {
      id: 'sales-mistakes',
      title: 'Common mistakes',
      blocks: [
        {
          points: [
            ['Two requests for one tool.', 'Put every part from the same tool on one request.'],
            ['Sending without the receipt date.', 'The 30 days run from the customer\'s receipt. A wrong date is a wrong validity.'],
            ['A new version without saying what changed.', 'Refused. The note is how the next reader understands the negotiation.'],
            ['Accepting by mail and not recording it.', 'Until "Customer accepted" is recorded, the change cannot be approved and the release deadline does not exist.'],
            ['Hiding a severity-3 risk.', 'The customer will not read about it. If it bites, the offer said nothing.'],
            ['Marking a team question solved yourself.', 'You answer; the asker judges the answer.'],
          ],
        },
      ],
    },
  ],
}

export const salesTasks: PracticeTaskSpec[] = [
  {
    key: 'sales_start_change',
    role: 'sales',
    title: 'Start a change request',
    status: 'ready',
    screen: { kind: 'start-change' },
    brief:
      'The customer sent a new drawing for the Rear Cladding (TR.807.425) in project T100: the ' +
      'clip tower is reinforced. Start the change request, with the reason from the ' +
      'customer\'s mail. The PEAK variant (TR.807.426) comes from the same tool and changes ' +
      'with it, so it belongs on the same request.',
    why:
      'One change request per tool family keeps one set of assessments and one revision per ' +
      'part. A request without its reason arrives at every department as a question.',
    fixture: ['Project T100 with the Rear Cladding, its PEAK variant and the Grille Carrier (exists today).'],
    pass: [
      { assert: 'a new change includes part TR.807.425 as lead item', hint: 'The Rear Cladding should lead the request: it is the part the drawing is for.' },
      { assert: 'the change includes TR.807.426', hint: 'The PEAK variant is missing. It comes from the same tool.' },
      { assert: 'the reason has at least 5 characters', hint: 'The reason is missing or too short to act on.' },
    ],
  },
  {
    key: 'sales_send_offer',
    role: 'sales',
    title: 'Build and send the first offer',
    status: 'needs-sandbox',
    screen: { kind: 'offer', change: 'CR-TRAIN-0013' },
    brief:
      'Costing is closed on CR-TRAIN-0013. Start the offer, switch on a 12 % margin, show the ' +
      'severity-3 sink mark risk to the customer, and send it. The customer confirmed receipt ' +
      'yesterday.',
    why:
      'The offer is the only thing the customer reads. A severity-3 risk the customer never ' +
      'saw is our problem alone when it happens.',
    fixture: [
      'CR-TRAIN-0013 in quoting, costing closed with two departments and one external position.',
      'One open risk concern, severity 3, "Sink marks". Like every risk, it starts hidden on the offer.',
      'Trainee acts as a Sales member.',
      'Quote plan seeded.',
    ],
    pass: [
      { assert: 'offer v1 has status sent', hint: 'The offer has not been sent yet.' },
      { assert: 'factor margin is enabled with value 12', hint: 'The margin factor is off or not 12 %.' },
      { assert: 'the sink mark risk has show true', hint: 'The severity-3 risk is not shown in the offer. The customer will not read about it.' },
      { assert: 'received_at is yesterday, so valid_until is received_at plus 30 days', hint: 'The receipt date is not the day the customer got it. The 30 days run from there.' },
      { assert: 'change.status is quoted', hint: 'The change did not move to "Quoted". Was the offer sent?' },
    ],
  },
  {
    key: 'sales_new_version',
    role: 'sales',
    title: 'Send a second version after a round',
    status: 'needs-sandbox',
    screen: { kind: 'offer', change: 'CR-TRAIN-0007' },
    brief:
      'On today\'s call the customer asked for a lower price on CR-TRAIN-0007. You agreed to ' +
      'drop the margin from 12 % to 8 %. Log the round, then send v2 and say what changed.',
    why:
      'Every round and every version is the negotiation\'s record. Months later somebody asks ' +
      'why the price moved, and the answer is on the change or nowhere.',
    fixture: [
      'CR-TRAIN-0007 quoted, offer v1 sent 5 days ago with margin 12 %.',
      'Trainee acts as a Sales member.',
    ],
    pass: [
      { assert: 'a negotiation round with channel call exists, tied to v1', hint: 'The call is not logged yet. "+ Record round" with the channel "Call".' },
      { assert: 'offer v2 is sent with margin 8', hint: 'v2 is not sent, or its margin is not 8 %.' },
      { assert: 'v2 change_note has at least 10 characters', hint: 'Say what changed against v1. It is required from v2 on.' },
      { assert: 'v1 status is superseded', hint: 'v1 should be superseded by v2 once v2 is sent.' },
    ],
  },
  {
    key: 'sales_issue_customer_decision',
    role: 'sales',
    title: 'Record the customer\'s decision on a validation issue',
    status: 'needs-sandbox',
    screen: { kind: 'validation-issue', change: 'CR-TRAIN-0010' },
    brief:
      'VI-1 on CR-TRAIN-0010 is a small gloss difference. PM routed it as a customer ' +
      'concession. The customer accepts it for good and sent a mail saying so. Record it.',
    why:
      'A concession without the customer\'s written word is our word against theirs at the ' +
      'next complaint. The issue closes only with the mail filed into it.',
    fixture: [
      'CR-TRAIN-0010 in_validation, VI-1 severity 1, route customer_concession, customer_inform true, no decision.',
      'Trainee acts as a Sales member.',
      'A sample mail file available to upload.',
    ],
    pass: [
      { assert: 'VI-1 has an attachment of kind customer_email', hint: 'The customer\'s mail is not filed into the issue. Use "Drop customer mail".' },
      { assert: 'customer_decision is accept_deviation with a note', hint: 'The decision is not "Accepts the deviation", or the note is empty.' },
      { assert: 'concession_until is empty', hint: 'The customer accepts it for good: leave "Concession until" empty.' },
      { assert: 'VI-1 status is accepted', hint: 'The issue is still open. Is the decision recorded?' },
    ],
  },
]
