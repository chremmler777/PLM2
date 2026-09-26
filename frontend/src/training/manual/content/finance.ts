import type { ContentChapter, PracticeTaskSpec } from './types'

//: Chapter 08, Finance. fin-assessment, fin-costsheet and fin-pnl replace the
//: stubs of the same id in ../chapters.tsx.

export const financeChapter: ContentChapter = {
  id: 'finance',
  number: '08',
  title: 'Finance',
  summary: 'The cost sheet: every rate that prices a change, its versions, its review, and what reaches the P&L. Sales keeps the rates; you check them.',
  roles: ['finance'],
  sections: [
    {
      id: 'fin-role',
      title: 'Your part in a change',
      blocks: [
        {
          lede:
            'Every hour, machine hour and sampling trial on a change is priced from one place: the ' +
            'cost sheet. Sales keeps the rates; you may change them too, and you check them. If a ' +
            'rate is wrong there, it is wrong in every costing, every offer and every P&L that uses it.',
        },
        {
          points: [
            ['You check', 'the hourly rates (one per department and plant), the machine rates per class, the sampling prices and the personnel overhead. Sales enters them; you may too.'],
            ['You publish', 'a new version with the date it takes over, together with Sales. Published versions are frozen.'],
            ['You review', 'the sheet on a fixed cycle. When it is due, "My Tasks" says so, for Sales and for you.'],
            ['You answer', 'when a costing line shows "No rate in the cost sheet": that line is not counted until Sales or you fill the rate.'],
          ],
        },
        {
          callout:
            'Rates are public by design: everybody in the organization can read the cost sheet. ' +
            'Only Sales, Finance or an admin can change it.',
        },
      ],
    },
    {
      id: 'fin-costsheet',
      title: 'The cost sheet and its versions',
      blocks: [
        {
          p:
            '"Cost sheet" is under Setup in the sidebar for accounts with the admin or engineer ' +
            'role. Everybody else opens it at the address ending in /cost-sheet. The page reads: ' +
            'hourly rates per department and plant, ' +
            'machine and sampling prices and personnel overhead, kept by Sales. A change is priced ' +
            'with the version valid on the day it was created; booked hours with the version valid ' +
            'on the booking day.',
        },
        {
          table: {
            head: ['Tab', 'Holds'],
            rows: [
              ['"Rates"', 'One hourly rate per department and plant; no positions. A plant row beats the all-plants row. An empty rate means "no rate yet". The effective rate includes the overhead.'],
              ['"Machines"', 'Hourly rate per machine class ("Machine classes", by tonnage). Below it, "Machines from MachineDB": the presses, synced with "Sync from MachineDB". A press may carry its own rate per version; a costing line that names it uses that rate, every other line the class rate.'],
              ['"Sampling"', 'Price of one trial per machine class: a flat price, or setup and run hours at the machine and labour rates.'],
              ['"Overheads"', 'Personnel overhead as a percentage or per hour, by plant and department.'],
            ],
          },
        },
        { shot: 'fin-cost-sheet', alt: 'The "Cost sheet" page on "Rates" with the version selector, "Current" chip and the rates table.' },
        {
          points: [
            ['Every department has a row.', 'A new draft gets a row with an empty rate for every department that can be routed on a change, per plant. "Add missing departments" adds the ones still missing. Nothing is guessed: an empty rate stays empty until somebody fills it, and the tab counts the rows that have no rate yet.'],
            ['Retired departments', 'keep their rows but are hidden. "Show retired" shows them, marked "Retired".'],
            ['One row per department and plant.', 'Adding a second one is refused: "... already has a rate at ... Edit that row instead."'],
            ['Sort and filter', 'every table like a spreadsheet: click a column heading to sort, use its filter button to pick values or a from/to range. "Clear filters" shows everything again.'],
          ],
        },
        { shot: 'fin-machines', alt: 'The "Machines" tab: "Machine classes" by tonnage above, "Machines from MachineDB" below with "Sync from MachineDB", the last sync time and one press with its own "Rate / h" next to the "Class rate / h".' },
        { h3: 'Changing a rate' },
        {
          steps: [
            { title: '"New draft"', body: 'Copies the latest published version. Only one draft exists at a time.' },
            { title: 'Edit the rows', body: 'Change, add or remove rows on any tab. "Changes vs previous" shows what differs.' },
            { title: '"Publish version"', body: 'Give "Valid from" and a note (for example the budget year or a wage agreement). The date must be after the valid-from date of the latest published version.' },
          ],
        },
        {
          points: [
            ['From the valid-from date', 'changes created from that day and hours booked from that day use the new rates. Changes created before keep the rates of their day: a later version never changes an existing change.'],
            ['A date in the past', 'asks "Publish backdated anyway". Changes created since then are priced with the new version where a line has no rate yet, and so are the hours booked since then. Lines already priced keep their rate.'],
            ['No differences', 'to the previous version: publishing is refused. There is nothing to publish.'],
          ],
        },
        { shot: 'fin-publish-dialog', alt: 'The "Publish version 3" dialog with "Valid from", the note and "2 rows differ from the previous version."' },
      ],
    },
    {
      id: 'fin-in-costing',
      title: 'What your rates do in a change',
      blocks: [
        {
          p:
            'On the "Costing" tab every change says which version prices it: "Priced from cost sheet ' +
            'v{v} ({plant}, {cur}): the version valid when the change was created on {date}". A ' +
            'change is always priced with the rates valid on the day it was created, whatever day a ' +
            'line is entered. Each costing line stores the rate and the version it was priced with, ' +
            'so a later version never rewrites a change or an offer already sent.',
        },
        {
          points: [
            ['"No rate in the cost sheet"', 'on a line: the department has no rate at that plant in the version of the change\'s creation date. The line is not counted. Fill the rate in a version valid on that date.'],
            ['Offer warning', '"Costing used cost sheet v1; this change is priced with v2 (valid on its creation date)": a line was priced before a backdated version. Sales decides whether to refresh.'],
            ['P&L actuals', 'price booked hours at the rate valid on the booking date.'],
            ['Currency', 'comes from the plant: the currency it quotes in. Silao quotes in USD and pays in MXN. The version carries the USD/MXN exchange rate; a Silao rate typed in MXN is converted with it, and MXN actual costs on a change are converted at the rate of the version valid when the change was created. Each conversion says the rate it used. Other currencies are not converted: a change costed in two currencies shows totals per currency.'],
          ],
        },
        { shot: 'fin-no-rate-line', alt: 'A costing line with the chip "No rate in the cost sheet" and "not counted".' },
      ],
    },
    {
      id: 'fin-review',
      title: 'The review cycle and plant currencies',
      blocks: [
        {
          p:
            'The page sets "Review every {n} months". When the current version is older, the cost ' +
            'sheet shows the banner "Cost sheet review due", costing says "Cost sheet v{v} is older ' +
            'than {m} months (review due {due})", and "My Tasks" shows "Review the cost sheet" ' +
            'to Sales and Finance. The current rates apply until a new version is published.',
        },
        {
          p:
            '"Plant currencies" lists each plant\'s currency, set from its location. Until Sales or ' +
            'Finance confirms it, the currency\'s tooltip reads "Currency set by location, Sales or ' +
            'Finance to confirm". Press "Confirm", or "Change" if the location guessed wrong.',
        },
        { shot: 'fin-review-banner', alt: 'The "Cost sheet review due" banner above the version selector, and "Plant currencies" with one unconfirmed plant.' },
      ],
    },
    {
      id: 'fin-assessment',
      title: 'Assessments and costing',
      blocks: [
        {
          p:
            'Finance has no assessment task and no costing input on a part change. The departments ' +
            'enter hours; your rates price them. If the scoping meeting routes Finance, you answer ' +
            'the checklist like every department: every row Yes or No, a Yes with what has to be done.',
        },
      ],
    },
    {
      id: 'fin-pnl',
      title: 'The P&L of a change',
      blocks: [
        {
          p:
            'Every change compares its offer with what happened. Planned figures are frozen when the ' +
            'customer accepts. Actuals come from booked hours times the rate valid that day, actual ' +
            'cost entries (supplier invoices, scrap) and validation issues by who pays.',
        },
        {
          table: {
            head: ['Line', 'Where it comes from'],
            rows: [
              ['Revenue', 'The accepted offer total, plus fixes quoted to the customer.'],
              ['Internal', 'Planned: costing hours at the snapshot rate. Actual: booked hours at the rate of the booking date.'],
              ['External', 'Planned: the chosen vendor quotes. Actual: "Add actual cost" entries.'],
              ['Validation issues', '"We pay", "Supplier pays" (recoverable, not in the margin) or "Customer pays".'],
            ],
          },
        },
        {
          p:
            'The "P&L" page lists the changes whose prices you may read, with "Offer revenue", ' +
            '"Planned cost", "Actual cost", the margins, "Variance" and "Slip". Prices on a change ' +
            'are shown to Sales, every Project Management member, the change lead and admins. ' +
            'Finance is not among them, on purpose: you check the rates, not the offers. Unless you ' +
            'lead a change, the page lists none for you.',
        },
      ],
    },
    {
      id: 'fin-mistakes',
      title: 'Common mistakes',
      blocks: [
        {
          points: [
            ['Backdating without thinking.', 'Changes created since that date (their lines without a rate) and time booked since then are priced with the new version. Lines already priced keep their rate, so costing and actuals drift apart.'],
            ['A rate without the overhead.', 'Check the effective rate column on "Rates".'],
            ['Leaving rates empty.', 'An empty rate is no rate: every line of that department at that plant is left out of the total. Filter "Rate / h" or tick "show only these" to find them.'],
            ['Leaving a plant currency unconfirmed.', 'Offers in that plant go out in a currency nobody checked.'],
            ['A Silao rate in MXN without the exchange rate.', 'Refused: "Enter the USD/MXN exchange rate of this version first".'],
            ['Ignoring the review task.', 'Costing keeps using old rates, and every offer inherits them.'],
          ],
        },
      ],
    },
  ],
}

export const financeTasks: PracticeTaskSpec[] = [
  {
    key: 'fin_publish_rate',
    role: 'finance',
    title: 'Publish a new Tool Engineer rate',
    status: 'needs-sandbox',
    replaces: 'fin_answer_checklist_row',
    screen: { kind: 'cost-sheet' },
    brief:
      'The new wage agreement raises the Tool Engineer rate at the Toccoa plant from 68.00 to ' +
      '71.50 per hour from the first of next month. Put it in a new version and publish it.',
    why:
      'A rate takes effect from its date, never before. Published on time, every change created ' +
      'from that day prices correctly. Published late and backdated, changes created since then ' +
      '(where a line has no rate yet) and time booked since then are priced with the new ' +
      'version, but lines already priced keep the old rate.',
    fixture: [
      'Cost sheet with one published version (v1) holding a Tool Engineer rate of 68.00 for plant Toccoa. No draft.',
      'Trainee acts as a Finance member.',
    ],
    pass: [
      { assert: 'a version v2 is published', hint: 'No new version is published yet.' },
      { assert: 'v2 holds Tool Engineer, Toccoa at 71.50', hint: 'The Tool Engineer rate for Toccoa in v2 is not 71.50.' },
      { assert: 'v2 valid_from is the first of next month', hint: 'The new rate starts on the first of next month, not today.' },
      { assert: 'v2 has a note of at least 5 characters', hint: 'Say why the rate changed. The note is what the next reader sees.' },
    ],
  },
  {
    key: 'fin_add_missing_rate',
    role: 'finance',
    title: 'Price a line that has no rate',
    status: 'needs-sandbox',
    screen: { kind: 'cost-sheet' },
    brief:
      'On CR-TRAIN-0014 a Packaging Engineer line shows "No rate in the cost sheet": the ' +
      'Toccoa plant has no Packaging Engineer rate. The agreed rate is 55.00 per hour from ' +
      'today. Add it so the line is counted.',
    why:
      'A line without a rate is left out of the total. The offer built on it is too low by ' +
      'exactly that amount.',
    fixture: [
      'Cost sheet v1 published with a valid-from before today, no Packaging Engineer row for Toccoa.',
      'No overhead row in v1 applies to Packaging Engineer at Toccoa, so the looked-up rate equals the base rate.',
      'CR-TRAIN-0014 in costing with one Packaging Engineer own-time line priced as missing.',
      'Trainee acts as a Finance member.',
    ],
    pass: [
      { assert: 'a published version valid today holds Packaging Engineer, Toccoa at 55.00', hint: 'No published version valid today has a Packaging Engineer rate of 55.00 for Toccoa.' },
      { assert: 'the rate lookup for that line now returns 55.00', hint: 'The costing line still finds no rate. Check the department and plant of the row, and that the version is valid on the day the change was created.' },
    ],
  },
  {
    key: 'fin_confirm_currency',
    role: 'finance',
    title: 'Confirm the plant currencies',
    status: 'needs-sandbox',
    screen: { kind: 'cost-sheet' },
    brief:
      'Two plants have a currency set by location. Toccoa is USD, which is right. Weissenburg ' +
      'shows USD too, which is wrong: it is EUR. Confirm the one and correct the other.',
    why:
      'The plant\'s currency is the currency of every rate and every offer there. Nobody else ' +
      'checks it.',
    fixture: [
      'Plants Toccoa (USD, unconfirmed) and Weissenburg (USD, unconfirmed).',
    ],
    pass: [
      { assert: 'Toccoa is USD and confirmed', hint: 'Toccoa is still unconfirmed.' },
      { assert: 'Weissenburg is EUR and confirmed', hint: 'Weissenburg should be EUR.' },
    ],
  },
]
