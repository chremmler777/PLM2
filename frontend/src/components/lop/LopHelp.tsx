/**
 * "How it works" on the project LOP page: the Project Manager's weekly
 * routine in a few steps, what the colours and numbers mean, and what a
 * responsible has to do. Plain text in a dialog; no data, no writes.
 */
import { useState, type ReactNode } from 'react'
import { CircleHelp } from 'lucide-react'
import Dialog from '../common/Dialog'
import { btnBase, btnSizes } from '../common/buttonStyles'
import { DEFAULT_STALE_DAYS } from '../../lib/lop'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-4 last:mb-0">
      <h3 className="mb-1.5 text-sm font-semibold text-slate-100">{title}</h3>
      {children}
    </section>
  )
}

const B = ({ children }: { children: ReactNode }) => <strong className="font-semibold text-slate-100">{children}</strong>
const list = 'list-decimal space-y-1.5 pl-5 text-sm text-slate-300'
const bullets = 'list-disc space-y-1.5 pl-5 text-sm text-slate-300'

export function LopHelpContent() {
  return (
    <div data-testid="lop-help">
      <Section title="What this list is for">
        <p className="text-sm text-slate-300">
          One list of open points per project. Every point has a department, one responsible person from the
          project team and a due date. You run it once a week; what does not move for two meetings goes to Cody.
        </p>
      </Section>

      <Section title="Project Manager: set the list up">
        <ol className={list}>
          <li><B>+ Task</B>: write the task, pick the department and the due date. The project-team member of that
            department becomes responsible. A department nobody is named for comes to you.</li>
          <li><B>Add from SEP</B>: pull in single SEP items or a whole gate. They do not come in by themselves.</li>
          <li><B>PDB topics</B> are listed live at the bottom. <B>Pin</B> the ones you want to track: you give the
            topic a name and a date, and from then on it counts like any other line. The topic itself stays in
            PDB (<B>Open in PDB</B>).</li>
          <li><B>PDB status</B> on top: <B>Show tools</B> opens the tool list. A red flag means the tool is not A/A
            and has no sampling booked. <B>Book in PDB</B> opens the sampling schedule.</li>
        </ol>
      </Section>

      <Section title="Project Manager: every week">
        <ol className={list}>
          <li><B>Start meeting</B>. The list is recorded as it stands: what is late, what had no update.</li>
          <li>Go through <B>Meeting view</B> from the top: overdue, due this week, waiting for your check, then
            the PDB topics.</li>
          <li>For every line: change it (comment, date, responsible), or press <B>Discussed</B> if there is
            nothing to change. Press <B>Escalate</B> if it needs Cody now.</li>
          <li>Lines reported <B>Done, please check</B>: <B>Confirm</B> closes the line, <B>Reopen</B> sends it back.
            Only you close lines.</li>
          <li><B>Close meeting</B>, then <B>Send minutes</B>. The project team gets what was closed, new, moved,
            overdue and without update.</li>
        </ol>
      </Section>

      <Section title="What escalates">
        <ul className={bullets}>
          <li>A line that is late or without update at <B>two meetings in a row</B> goes on Cody's list.</li>
          <li>A line you mark <B>Escalate</B> goes there at once.</li>
          <li>Open lines and <B>no meeting for more than 10 days</B>: the project itself is escalated, with your name.</li>
          <li>Escalations show as a <B>red number</B> on My Tasks, for the responsible and for you.</li>
        </ul>
      </Section>

      <Section title="If you are responsible for a line">
        <ul className={bullets}>
          <li>Your lines are on <B>My Tasks</B>, group LOP. Late ones first.</li>
          <li>Open the line and write a short comment when something moves. No update
            for {DEFAULT_STALE_DAYS} days counts against the line.</li>
          <li>When it is finished press <B>Done, please check</B>. The Project Manager confirms.</li>
          <li>You cannot move the due date yourself. Tell the Project Manager why; a moved date stays visible.</li>
        </ul>
      </Section>

      <Section title="What the numbers measure">
        <ul className={bullets}>
          <li><B>Name and date</B>: share of open lines that have both. This is the first number on the LOP overview.</li>
          <li><B>On time</B> is measured against the <B>first</B> due date, so moving a date does not help.</li>
          <li><B>Not touched</B>: lines that were in the meeting and were neither changed nor marked.</li>
        </ul>
      </Section>
    </div>
  )
}

export default function LopHelp() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" data-testid="lop-help-button" className={`${btnBase} ${btnSizes.sm} border border-sky-500 bg-sky-900/40 text-sky-200 hover:bg-sky-800/60 hover:text-white`}
        onClick={() => setOpen(true)}>
        <CircleHelp aria-hidden="true" size={14} />How it works
      </button>
      <Dialog open={open} onClose={() => setOpen(false)} size="xl" title="Project LOP: how it works"
        description="For the Project Manager who runs the list, and for everyone who has a line on it.">
        <LopHelpContent />
      </Dialog>
    </>
  )
}
