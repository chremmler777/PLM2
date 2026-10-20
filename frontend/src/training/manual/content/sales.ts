import type { ContentChapter, PracticeTaskSpec } from './types'
import { MEXICO_NOT_IN_USE_TEXT } from '../../../lib/plantNotInUse'

//: Chapter 04, Sales. sales-start, sales-documents and sales-quote replace
//: the stubs of the same id in ../chapters.tsx.

export const salesChapter: ContentChapter = {
  id: 'sales',
  number: '04',
  title: 'Sales',
  summary: 'Starting a change request, the offer, negotiation, the customer\'s answer, every customer contact after it, and the rates on the cost sheet.',
  roles: ['sales'],
  sections: [
    {
      id: 'sales-role',
      title: 'Your part in a change',
      blocks: [
        {
          lede:
            'You are the customer contact. Project Management owns the change from capture to close ' +
            '(the project\'s lead PM leads it); you start the request (or PM does on your behalf), you ' +
            'build and send the offer, you log every round, and anything the customer has to hear ' +
            'after acceptance goes through you.',
        },
        {
          table: {
            head: ['Stage', 'What you do'],
            rows: [
              ['Captured', 'Start the request with its reason, parts, documents and quote deadline. The lead (the project\'s lead PM) hands it over; "Create and hand over" does it for them when the capture is complete.'],
              ['Scoping', 'Answer the team\'s questions for the customer. Send the rejection letter if the change is rejected.'],
              ['Costing', 'Nothing to enter. You see every department\'s numbers and may start the rough timing.'],
              ['Quote creation', 'Build the offer: timing, price, risks, document. Send v1.'],
              ['Quoted', 'Log each round, send new versions, record the customer\'s answer.'],
              ['Timing', 'Confirm the plan for Sales, publish the validated plan to the customer.'],
              ['Implementing', 'Tell the customer about escalated deviations.'],
              ['Validation', 'Record the customer\'s decision on a validation issue, quote a fix the customer pays, mark "Customer informed of the implementation date / first shipment" done with the customer mail or its reference.'],
            ],
          },
        },
        {
          p:
            'Project Management owns the change process, from capture to close: the project\'s ' +
            'lead PM leads every change on the project and hands it over to scoping, follows it up ' +
            'and escalates. You keep the customer side: the quote deadline, the offer and the ' +
            'customer\'s answer. You may start a change for the PM (and the PM for you); the hand-over ' +
            'row is then the lead\'s, and you see it as backup with the lead\'s name and "You supply the ' +
            'customer\'s facts" while the description, quote deadline or customer file is missing. ' +
            'A customer change has a Sales contact, shown on the Status card and in the change ' +
            'list: you when you started it, else the project\'s Sales contact. With neither it reads ' +
            '"No Sales contact: all of Sales", and anyone in Sales takes it with "Pick a Sales contact". All of Sales still ' +
            'sees the Sales tasks, with the contact\'s name on them, and anyone in Sales may act. ' +
            'Hand a change to a colleague with "change" beside "Sales contact".',
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
            { title: 'Quote deadline', body: 'When the customer expects the offer. Optional on the form. The hand-over to scoping asks for it, and for a change lead; without them the hand-over needs an approved override.' },
            { title: 'Customer documents', body: 'Drop the drawing, the mail, the specification. They are filed as the customer\'s files; one customer file (or a filed customer mail) is required before scoping.' },
            { title: 'Urgent', body: 'Tick "Urgent" only with a need-by date, the reason (line stop, safety, quality escape, launch date, customer demand, other) and the evidence (mail, 8D number, file). Without them the change is not created. Tasks on an urgent change are due in 1 working day; the header shows "Need-by 24 Oct, 8 wd left, now: Scoping".' },
            { title: 'Create change', body: 'The form tells you if it is "Ready to hand over to scoping" or what is missing. When it is ready, "Create and hand over" puts it into scoping in the same click; "Create as draft" keeps it with you.' },
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
            ['Customer mails', 'are filed on the change as a tracked list. Everybody may upload one; you are the customer contact.'],
            ['A question from the team', 'arrives as an open question at scoping. Answer it "Confirmed" or "Assumed". A customer question is "Confirmed" only by the customer\'s mail (pick it from the filed mails) or document. Without it answer "Assumed": the value with its unit and the risk if it is wrong. You then get "Confirm an assumption" in My Tasks, due in 5 working days. The asker or PM marks the question solved; you never do.'],
            ['A question from an assessment', 'a department that is blocked asks it from its own assessment ("Question from Tool Engineer"). It holds only that department\'s submit, so answer it within the task\'s due date the same way: "Confirmed" or "Assumed".'],
            ['"Not yet"', 'from the scoping meeting keeps the change in scoping while the open questions wait for their answers.'],
            ['"Tell customer: new date or start at risk?"', 'appears at once when the scoping meeting proceeds an urgent customer change and says the need-by is not realistic (only with start at risk, or no with a proposed date). Tell the customer, then record it with the filed mail or a reference ("Customer told").'],
            ['A new customer index', 'A full ECR started from a new index arrives with the customer files attached and you as Sales contact: set the quote deadline. When a new index replaces the old one in a running change, answer "New index: deadline holds?": "Holds" with the customer\'s mail or a reference, "New date" with the date and the mail, or "Not asked yet" (an assumption you confirm within 5 working days).'],
            ['"Customer notification or offer needed?"', 'appears when an internal change became a customer change (Quality said parameters, tool, material or cycle time changed, or a customer index arrived). Answer "Notification only" with the filed mail or a reference (the customer is told, the money stays ours: the change goes back to internal with its earlier lead and internal approval; this is the only way back, the lead cannot switch it), or "Offer needed" with the quote deadline (the change takes the quote path; past approval the price stays open until a supplement is accepted). The change cannot proceed before you answer.'],
            ['"Set the quote deadline"', 'appears when Development started a full ECR from a new customer index: the change is already in scoping, the lead scopes while you set the deadline. It is owed before assessment.'],
            ['"Copy mail text"', 'on a customer question (card and task row): the question, the part and what the answer decides, ready for your mail to the customer. File the reply on the change, then answer "Confirmed" with that mail.'],
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
            ['"Ready to quote"', 'is the notice you get when costing closes on your change: the offer is yours from then on. Without a Sales contact every Sales member gets it.'],
            ['"estimated" on a line', 'the cost stands on a department\'s estimate, not on a supplier quote yet. If the quote comes in higher later, the price opens again (below).'],
            ['"Quote above the estimate: supplement or absorb"', 'in My Tasks: a supplier quote came in above the estimate an offer was built on ("Estimate low by 4200.00"). Send a supplement for the difference, or ask to absorb it with a reason (a PM member or Management decides). The change cannot close while this price is open.'],
          ],
        },
        { h3: 'The document' },
        {
          p:
            'The PDF carries the KTX Group US Corp. letterhead of the Toccoa site, the offer number ' +
            '(change number, Q, version), the scope, the price, changeover, timing with a draft ' +
            'disclaimer, the risks you chose and the terms. Every date on it reads like "26 Sep ' +
            '2026", for every customer; amounts follow the offer currency. The validity is fixed: 30 ' +
            'days from the customer\'s receipt. "Preview PDF" shows the draft with a DRAFT watermark.',
        },
        {
          p:
            'Sales signs the offer. The version you send carries your name and your title (else ' +
            '"Sales"), and keeps it for good. If a PM lead or an admin sends it, the project\'s Sales ' +
            'responsible signs, else the "Sales" line alone. A draft shows "Signed by (preview)" ' +
            'with who would sign if it were sent now: you when you are in Sales, otherwise the ' +
            'project\'s Sales responsible.',
        },
        { shot: 'sales-offer-pdf', alt: 'Page 1 of an offer PDF: letterhead, "OFFER" with number and valid-until date, recipient and "1. Scope of change".' },
        { h3: 'Sending' },
        {
          p:
            '"Send offer" asks when the customer received it ("Received by the customer on"). The ' +
            'offer is valid 30 days from that date. Sending v1 sets the quoted price and moves the ' +
            'change to "Quoted".',
        },
        {
          points: [
            ['"Goes out on index"', 'names the index of every part. When the customer already sent a newer one ("customer sent D"), the change is still on the old one: get the new index triaged onto the change first, or send knowing it.'],
            ['"Check before it goes out"', 'lists the unconfirmed assumptions (value, what happens if it is wrong, who confirms by when) and the positions priced on an estimate. The customer pays on them: confirm what you can first.'],
            ['"High risks not on the offer"', 'a severity-3 risk you keep hidden needs a reason and a sentence to go out (it is logged). Show it, with a surcharge if it costs, and no reason is asked.'],
          ],
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
            { title: '"Customer accepted"', body: 'Nothing is preselected. Pick the PO or the customer\'s mail filed on the change, or type the PO number. Answer "PO matches offer vN exactly?" (no: name the parts that differ and any other P/Ns), tick "This mail says yes to vN at <total>", check the "Release deadline" (prefilled from the need-by or the weeks from order) and "Confirm acceptance". A part index that moved since the offer is shown as a warning.' },
            { title: 'A lower price than the last version', body: 'When the version the customer accepts is below the one you sent before it, pick why (higher volume, competitor, goodwill, error in the offer) and say it in a sentence. A Project Management or Management member gives the OK; the approval waits for it.' },
            { title: 'Or "Still talking"', body: 'Set the next contact date (5 working days by default). Your task stays, due on that date. A new price is a new version.' },
            { title: 'Or "Customer declined"', body: 'Name the customer\'s reference or pick the filed mail. This cannot be undone: the change is rejected and you get the task to send the rejection letter.' },
            { title: 'Sign-offs', body: 'PM and Quality then give their sign-offs. The change is approved on its own with the last of the three.' },
          ],
        },
        { shot: 'sales-customer-response', alt: 'The "Customer answer" block on v2 with "Customer accepted", "Customer declined" and the sign-off buttons below.' },
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
            ['Validation issue, customer to be informed:', '"Record customer decision": "Accepts the deviation", "Requires a fix", "New timing" or "Pending". When Quality requests a concession you, the Sales contact, get "Ask the customer about the concession for VI-n and file the mail" (due in 2 working days): ask the customer ("Pending" records that you asked), then file the customer\'s mail into the issue; that ends your task, a Quality member then decides it (you get no "Accepts the deviation" there). A failed weight check is told to you; the quote task opens only when the weight is more than 2 % off the estimate.'],
            ['A fix the customer pays:', 'you get the task to quote it. "Quote the fix", then "Fix quoted to the customer".'],
            ['Release:', 'mark "Customer informed of the implementation date / first shipment" done with the customer mail or its reference.'],
            ['"Ask to start at risk"', 'urgent changes only, before the PO: file the customer\'s go-ahead (the mail or its reference) on the Offer tab. Quality adds a line of quality risks, a Project Management member approves (not you). The change is approved and the work starts; you still send the offer (Offer tab, "Start the offer", then "New version") and record the customer\'s answer (an answer needs the offer sent first): the price is open until the customer accepts it or it is absorbed. Not urgent? The lead or an admin marks the change urgent first.'],
            ['Evidence of the customer', 'pick the customer\'s mail or file filed on the change, or type the PO number or the mail reference. A file uploaded as an internal document counts only when you tick "This file came from the customer".'],
            ['"Customer wants to add or change something"', 'from "Quoted" on, on the Offer tab: the P/N (if a part), what, by when, and the customer\'s mail (or its reference). The lead accepts it (the departments re-cost it, the card says who it waits for) or refuses it (you tell the customer and record the mail). When the last department re-costed, you send a new version (after approval: a supplement); sending it while quoted clears the customer\'s earlier yes, so the customer answers the new version. Every department said "No cost impact"? Nothing to price: confirm to the customer that it comes at no price change and record the mail ("Confirmed to the customer: no price change"). A version sent before re-costing ends says "subject to final costing". Information missing? The lead (or you) asks the customer from the card: you get "Ask the customer: scope change" with the mail text to copy, and file the customer\'s answer with the mail; the lead decides after it. Approval waits while a scope change opened before approval is open (a PO that differs at the customer\'s yes opens one too); one opened after approval opens the price instead.'],
            ['"Send supplement"', 'once the change is approved, what changes in price goes to the customer as a supplement: only the positions that changed since the accepted offer. The change keeps its status; the price is open until the customer accepts the supplement (record it under "Customer answer" like any offer) or it is absorbed. Declined: My Tasks shows "Price open: absorb or send a new version" (due in 5 working days); absorb it with a reason that names the amount or the part, send a new version, or the lead puts the change on hold. A lower version than the last accepted one (or the highest sent since), also a lower piece price, needs a reason and the OK of PM or Management.'],
          ],
        },
        { shot: 'sales-issue-decision', alt: 'The customer decision form on a validation issue with "Accepts the deviation" selected and a customer mail filed.' },
      ],
    },
    {
      id: 'sales-rates',
      title: 'Keeping the rates: the cost sheet',
      blocks: [
        {
          p:
            'Sales keeps the cost sheet: one hourly rate per department per plant, the machine and ' +
            'sampling prices and the overhead. Finance and admins may change them too. Project ' +
            'Manager and Management members read them; nobody else sees the sheet (their costing ' +
            'lines still look the rates up). The page is "Cost sheet", at the address ending in /cost-sheet.',
        },
        {
          steps: [
            { title: '"New draft"', body: 'Copies the latest published version. Every department that can be routed on a change gets a row per plant; a new one has an empty rate.' },
            { title: 'Fill the rates', body: 'On "Rates", one row per department and plant. "Add missing departments" adds rows still missing. The tab says how many rows have no rate yet.' },
            { title: '"Publish version"', body: 'With "Valid from" and a note. From that day on, new changes are priced with it.' },
          ],
        },
        {
          points: [
            ['A change keeps its rates.', 'It is priced with the version valid on the day it was created. A later version never changes a change or an offer already sent.'],
            ['An empty rate is no rate.', 'Costing shows "No rate in the cost sheet" and leaves the line out of the total: the offer is too low.'],
            ['Machines come from MachineDB.', 'On "Machines", "Sync from MachineDB" lists the presses. A press may carry its own rate; without one its class rate applies.'],
            ['Silao works in two currencies.', 'It quotes in USD and pays in MXN. Type the version\'s rate under "Exchange rates" (1 USD = 17.30 MXN) on the draft. A Silao rate may then be typed in the USD or the "Local / h" column: the typed number is kept, the other says "calculated". Publishing freezes the exchange rate with the rates. ' + MEXICO_NOT_IN_USE_TEXT],
            ['MXN actual costs', 'on a Silao change are converted to USD at the exchange rate of the change\'s own version; the P&L says so, with the rate. Money without a rate in the version is never added.'],
            ['Retired departments', 'keep their rows, hidden until "Show retired".'],
            ['Sort and filter', 'every table like a spreadsheet: a column heading sorts, its filter button narrows by value or range.'],
          ],
        },
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
            ['Starting a KTX Weissenburg or Solingen change.', 'Project Management starts those. Send the request to PM.'],
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
    title: 'File the customer\'s yes to a concession',
    status: 'needs-sandbox',
    screen: { kind: 'validation-issue', change: 'CR-TRAIN-0010' },
    brief:
      'VI-1 on CR-TRAIN-0010 is a small gloss difference. Quality requested a concession on ' +
      'VI-1; the customer accepts it for the next 500 parts and sent a mail saying so. File it ' +
      'so Quality can decide (for that quantity or until a date, never for good).',
    why:
      'A concession without the customer\'s written word is our word against theirs at the ' +
      'next complaint. Quality decides the concession only once the mail is filed into the issue.',
    fixture: [
      'CR-TRAIN-0010 in_validation, VI-1 severity 1, concession requested by Quality (route customer_concession, concession_requested_by a Quality member), customer_inform true, no decision.',
      'Trainee acts as a Sales member.',
      'A sample mail file available to upload.',
    ],
    pass: [
      { assert: 'VI-1 has an attachment of kind customer_email', hint: 'The customer\'s mail is not filed into the issue. Use "Drop customer mail".' },
      { assert: 'VI-1 status is route_decided (waiting for Quality)', hint: 'The concession is Quality\'s decision: filing the mail is your part.' },
    ],
  },
]
