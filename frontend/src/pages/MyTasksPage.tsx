/**
 * MyTasksPage - everything waiting on the caller, in one list
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useDepartments, useMyTasks } from '../hooks/queries/useWorkflows';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import EscalationsCard from '../components/EscalationsCard';
import { rasicColors } from '../lib/constants';
import { formatCalendarDate, formatDate } from '../lib/format';
import { DeadlineChip } from '../components/changes/DeadlineChip';
import { btnSm } from '../components/common/buttonStyles';
import EmptyState from '../components/common/EmptyState';
import { toastError } from '../lib/apiError';
import { BookOpen, ClipboardList, FileText } from 'lucide-react';
import { STATUS_LABELS } from '../lib/changeStatus';
import { humanize, taskKindLabel } from '../lib/humanLabels';
import { dueNote, foldChangeTasks, lateHint, foldWorkflowTasks, isBackup, mainFirst, type FoldedWorkflowTask } from '../lib/myTasks';
import BackupChip from '../components/common/BackupChip';
import client from '../api/client';
import { changesApi } from '../api/changes';
import CustomerCopy from '../components/changes/scoping/CustomerCopy';
import { t } from '../i18n/cmLabels';
import type { ChangeTask } from '../types/change';
import { projectLabel } from '../lib/project';
import { toast } from 'sonner';
import FormPanel from '../forms/FormPanel';
import IntakeSection from '../components/intake/IntakeSection';
import CostSheetReviewTask from '../components/costSheet/CostSheetReviewTask';
import { useMyTaskCounts } from '../hooks/queries/useOpenTaskCount';

interface MyLessonAction {
  id: number;
  description: string;
  due_date: string | null;
  overdue: boolean;
  lesson_id: number;
  lesson_title: string;
  lesson_status: string;
  lesson_severity: string;
}

function LessonActionsSection() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: actions = [] } = useQuery({
    queryKey: ['my-lesson-actions'],
    queryFn: async () => (await client.get('/v1/lessons/my-actions')).data as MyLessonAction[],
    refetchInterval: 60_000,
  });

  const complete = useMutation({
    mutationFn: async (actionId: number) =>
      client.patch(`/v1/lessons/actions/${actionId}`, { status: 'done' }),
    onSuccess: () => {
      toast.success('Lesson action marked done');
      queryClient.invalidateQueries({ queryKey: ['my-lesson-actions'] });
    },
    onError: (error: unknown) => toastError(error, 'Could not mark the lesson action done'),
  });

  if (actions.length === 0) return null;

  return (
    <div>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
        <BookOpen aria-hidden="true" size={14} className="text-slate-400" />Lesson actions ({actions.length})
      </h2>
      <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 bg-slate-900">
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Action</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Lesson</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Due</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {actions.map((a) => (
              <tr key={a.id} className="border-b border-slate-700 last:border-0 hover:bg-slate-700/30">
                <td className="px-4 py-3 text-slate-100">{a.description}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => navigate(`/lessons?lesson=${a.lesson_id}`)}
                    className="text-sky-400 hover:text-sky-300 underline underline-offset-2 text-left"
                  >
                    {a.lesson_title}
                  </button>
                  <span className="text-xs text-slate-500 ml-2">{a.lesson_status.replace(/_/g, ' ')}</span>
                </td>
                <td className="px-4 py-3 text-xs"><DueCell due={a.due_date} overdue={a.overdue} /></td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => complete.mutate(a.id)}
                    disabled={complete.isPending}
                    className={btnSm.secondary}
                  >
                    Mark done
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface MySepItem {
  id: number;
  item_no: number;
  title_en: string;
  department: string;
  project_id: number;
  project_name: string;
  gate_code: string;
  gate_target_date: string | null;
}

function SepItemsSection() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: items = [] } = useQuery({
    queryKey: ['my-sep-items'],
    queryFn: async () => (await client.get('/v1/sep/my-items')).data as MySepItem[],
    refetchInterval: 60_000,
  });

  const markDone = useMutation({
    mutationFn: async (itemId: number) =>
      client.patch(`/v1/sep/items/${itemId}`, { status: 'done' }),
    onSuccess: () => {
      toast.success('Work package done');
      queryClient.invalidateQueries({ queryKey: ['my-sep-items'] });
      queryClient.invalidateQueries({ queryKey: ['sep'] });
    },
    onError: (error: unknown) => toastError(error, 'Could not mark the work package done'),
  });

  if (items.length === 0) return null;

  return (
    <div>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
        <ClipboardList aria-hidden="true" size={14} className="text-slate-400" />SEP work packages ({items.length})
      </h2>
      <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 bg-slate-900">
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Work Package</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Project / Gate</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Gate Target</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id} className="border-b border-slate-700 last:border-0 hover:bg-slate-700/30">
                <td className="px-4 py-3 text-slate-100">
                  {i.title_en}
                  <span className="text-xs text-slate-500 ml-2">{i.department}</span>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => navigate(`/projects/${i.project_id}`)}
                    className="text-sky-400 hover:text-sky-300 underline underline-offset-2 text-left"
                  >
                    {i.project_name}
                  </button>
                  <span className="text-xs text-slate-500 ml-2">{i.gate_code}</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  {formatCalendarDate(i.gate_target_date)}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => markDone.mutate(i.id)}
                    disabled={markDone.isPending}
                    className={btnSm.secondary}
                  >
                    Mark done
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


interface MyForm {
  id: number;
  key: string;
  title: string;
  status: string;
  reason: string;
  project_id: number;
  project_name: string;
  updated_at: string;
}

function FormsSection() {
  const navigate = useNavigate();
  const [open, setOpen] = useState<number | null>(null);

  const { data: forms = [] } = useQuery({
    queryKey: ['my-forms'],
    queryFn: async () => (await client.get('/v1/forms/my-forms')).data as MyForm[],
    refetchInterval: 60_000,
  });

  if (forms.length === 0) return null;

  return (
    <div>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
        <FileText aria-hidden="true" size={14} className="text-slate-400" />SEP forms ({forms.length})
      </h2>
      <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <tbody>
            {forms.map((f) => (
              <tr key={f.id} className="border-b border-slate-700 last:border-0">
                <td className="px-4 py-3 text-slate-100">
                  <button onClick={() => setOpen(f.id)} className="hover:underline text-left">{f.title}</button>
                  <span className="text-xs text-slate-500 ml-2">{f.status}</span>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => navigate(`/projects/${f.project_id}`)}
                    className="text-sky-400 hover:text-sky-300 underline underline-offset-2"
                  >
                    {f.project_name}
                  </button>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">{formatDate(f.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open !== null && <FormPanel key={open} instanceId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}


// Kinds whose row may name its own tab (it wins over TASK_TAB).
const OWN_TAB_KINDS = new Set(['obtain_info'])

// Where each kind of change task is actually done, and how it reads in a list.
const TASK_TAB: Record<string, string> = {
  kickoff: '', hold_resume: '', scoping_wrapup: '?tab=scoping',
  impact_confirm: '?tab=impacted', customer_response: '',
  obtain_info: '?tab=scoping', close_question: '?tab=scoping',
  confirm_assumption: '?tab=scoping', ppap_decision: '?tab=scoping',
  customer_flip: '?tab=scoping',
  assessment_recheck: '?tab=assessments', index_decision: '?tab=assessments',
  index_deadline: '?tab=assessments', index_deadline_confirm: '?tab=assessments',
  need_by_tell: '', set_quote_deadline: '', pick_impacted: '?tab=impacted',
  send_rejection: '?tab=scoping',
  costing_input: '?tab=costing', estimate_low: '?tab=commercial', estimate_check: '?tab=costing',
  create_quote: '?tab=commercial',
  // Stage 7 lives on the implementation tab: Scheduling decides there, Sales
  // publishes from the same card.
  bank_build: '?tab=implementation',
  publish_plan: '?tab=implementation',
  // Stage 8 lives on the same tab: the department reports there, Sales
  // escalates from the same blocks.
  progress_report: '?tab=implementation',
  escalate_risk: '?tab=implementation',
  // Stage 9 shares the tab: the department confirms its checks there, and the
  // weight delta that sends Sales back to the quote is stated on the same panel.
  // The checks live on the Release tab (C3 fix).
  validation_check: '?tab=release',
  update_quote: '?tab=implementation',
  // C3: decisions and the run team's onward hop, on the overview's
  // why-blocked panel; the internal approval on the commercial tab.
  deviation_decision: '?tab=overview', sign_off: '?tab=overview',
  advance: '?tab=overview', internal_approval: '?tab=commercial',
  // the routing change is decided on the assessments tab; a 'not feasible'
  // answer on the overview's why-blocked panel (override, reroute, reject)
  routing_deviation_decision: '?tab=assessments', not_feasible: '?tab=overview',
};

/** Where a task row leads: its tab, plus `task=<kind>` so the change opens
 *  with the task card ("Your part: ..., due ... Next: ..."). */
function taskLink(task: Pick<ChangeTask, 'kind' | 'change_id' | 'department_id' | 'target_tab' | 'deviation_id' | 'side'>): string {
  // C8: a question asked from an assessment names its own tab (the asking
  // department's bucket), the scoping tab only reads it there
  const tab = (OWN_TAB_KINDS.has(task.kind) && task.target_tab)
    ? `?tab=${task.target_tab}`
    : TASK_TAB[task.kind] ?? (task.target_tab ? `?tab=${task.target_tab}` : '');
  const params = new URLSearchParams(tab.replace(/^\?/, ''));
  params.set('task', task.kind);
  if (task.department_id != null) params.set('dept', String(task.department_id));
  // two overrides or both sign-off sides on one change: the card shows this one
  if (task.deviation_id != null) params.set('dev', String(task.deviation_id));
  if (task.side) params.set('side', task.side);
  return `/changes/${task.change_id}?${params.toString()}`;
}

// the backend's kickoff_missing words (and the older short keys)
const KICKOFF_ITEM: Record<string, string> = {
  description: 'kickoff.description', attachment: 'kickoff.attachment',
  'at least one attachment': 'kickoff.attachment', date: 'deadline.quote',
  'quote deadline': 'deadline.quote', 'change lead': 'next.item.lead',
  // §2 capture
  'customer file': 'next.item.customer_file', 'what is wrong today': 'next.item.problem',
  target: 'next.item.target', 'need-by date': 'next.item.need_by',
  'urgent reason and evidence': 'next.item.urgent_reason',
};

const kickoffHint = (missing?: string[]): string => {
  const parts = (missing ?? []).map((m) => (KICKOFF_ITEM[m] ? t(KICKOFF_ITEM[m]) : m));
  return parts.length === 0
    ? t('tasks.hint.kickoffReady')
    : t('tasks.hint.kickoff').replace('{x}', parts.join(', '));
};

const taskHint = (task: ChangeTask): string | null => {
  switch (task.kind) {
    case 'assessment':
      // R5/R18: a consulted department owes no submit, only its check items
      return (task.checks_open ?? 0) > 0
        ? t('tasks.hint.checkItems').replace('{n}', String(task.checks_open))
          .replace('{x}', task.department_name ?? '')
        : null;
    case 'estimate_check':
    case 'estimate_low':
      // the backend's brief names the positions and the amount
      return task.hint ?? null;
    case 'kickoff':
      return kickoffHint(task.missing);
    case 'hold_resume':
      return task.reason?.trim()
        ? t('tasks.hint.hold_resume').replace('{x}', task.reason.trim())
        : t('tasks.hint.hold_resumeNoReason');
    case 'scoping_wrapup': {
      // C33: "Not yet: waiting for 2 answers (Sales Thu, Process Fri)", then
      // what else holds proceed with its owner; "Ready: proceed" only when
      // nothing does (the backend's proceed_holds).
      if (task.open_questions != null && !task.has_decision) {
        const parts = [
          ...(task.open_questions > 0
            ? [t('tasks.hint.scopingWaiting').replace('{n}', String(task.open_questions))
              .replace('{x}', (task.waiting_on ?? []).join(', '))] : []),
          ...((task.holds ?? []).length > 0
            ? [t('tasks.hint.scopingHeld').replace('{x}', (task.holds ?? [])
              .map((h) => t(`proceed.hold.${h.key}`).replace('{who}', h.owner)).join(', '))] : []),
        ]
        return parts.length > 0 ? parts.join(' · ') : t('tasks.hint.scopingReady')
      }
      const open = [
        // null: no manual confirm (switch off), nothing to confirm.
        ...(task.impact_confirmed === false ? [t('tasks.hint.impactOpen')] : []),
        ...(task.has_decision ? [] : [t('tasks.hint.decisionOpen')]),
      ];
      return open.length > 0 ? open.join(', ') : t('tasks.hint.wrapup');
    }
    case 'impact_confirm':
      return t('tasks.hint.impact_confirm');
    case 'send_rejection':
      // Two steps, one row: write the letter, then confirm it went out.
      return task.has_letter
        ? t('tasks.hint.send_rejection_send') : t('tasks.hint.send_rejection_letter');
    case 'costing_input':
      return t('tasks.hint.costing_input');
    case 'create_quote':
      return t('tasks.hint.create_quote');
    case 'bank_build':
      return t('tasks.hint.bank_build');
    case 'publish_plan':
      return t('tasks.hint.publish_plan');
    case 'progress_report':
      return t('tasks.hint.progress_report');
    case 'escalate_risk':
      return t('tasks.hint.escalate_risk');
    case 'validation_check':
      return t('tasks.hint.validation_check');
    case 'update_quote':
      return t('tasks.hint.update_quote');
    case 'deviation_decision':
      return task.reason?.trim() || t('tasks.hint.deviation_decision');
    case 'sign_off': {
      const base = task.offer_version != null
        ? t('tasks.hint.sign_off_v').replace('{v}', String(task.offer_version))
        : t('tasks.hint.sign_off');
      if (task.side !== 'pm' || task.offer_total == null) return base;
      // §7 [R3]: the PM signs knowing the total, the margin move and the assumptions
      const money = `${task.offer_total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${task.offer_currency ?? ''}`.trim();
      const margin = task.margin_pct != null ? `, ${t('tasks.hint.margin').replace('{m}', task.margin_pct.toFixed(1))}` : '';
      const delta = task.margin_delta_pts != null && task.prev_version != null
        ? ` ${t('tasks.hint.marginDelta').replace('{d}', `${task.margin_delta_pts > 0 ? '+' : ''}${task.margin_delta_pts.toFixed(1)}`).replace('{v}', String(task.prev_version))}`
        : '';
      const assumed = task.assumed_open ? `; ${t('tasks.hint.assumedOpen').replace('{n}', String(task.assumed_open))}` : '';
      return `${base}: ${money}${margin}${delta}${assumed}`;
    }
    case 'internal_approval':
      return t('tasks.hint.internal_approval');
    case 'routing_deviation_decision':
      return t('tasks.hint.routing_deviation_decision');
    case 'not_feasible':
      return task.departments?.length
        ? t('tasks.hint.not_feasible').replace('{x}', task.departments.join(', '))
        : task.hint ?? null;
    case 'advance':
      return t('tasks.hint.advance').replace(
        '{x}', task.to_status ? (STATUS_LABELS[task.to_status] ?? humanize(task.to_status)) : '-');
    case 'obtain_info':
    case 'close_question': {
      // The question (or the answer to it) is the brief; when several are open,
      // say how many so the row does not read as a single job.
      const newest = task.reason?.trim() || t(`tasks.hint.${task.kind}`);
      return (task.question_count ?? 0) > 1
        ? `${t('tasks.hint.questionsOpen').replace('{n}', String(task.question_count))} ${newest}`
        : newest;
    }
    case 'customer_response':
      return t('tasks.hint.customer_response');
    case 'confirm_assumption':
      return t('tasks.hint.confirm_assumption').replace('{x}', task.reason ?? '');
    case 'ppap_decision':
      return t('ppap.question');
    case 'customer_flip':
      return t('flip.title');
    case 'assessment_recheck':
      return task.reason ?? null;
    case 'index_decision':
      return t('tasks.kind.index_decision');
    case 'index_deadline':
    case 'index_deadline_confirm':
    case 'need_by_tell':
      return t(`tasks.kind.${task.kind}`);
    default:
      return null;
  }
};

/** The due cell: the same chip as the changes list ("in 5 d", "2 d overdue"),
 *  the date ("25 Sep 2026") under it; "-" when undated. The backend's overdue
 *  flag decides the color. C20: what the date runs against, "(quote deadline
 *  20 Oct)" or "(urgent)", and "Late" once due + 1 working day passed (the
 *  department and the lead see it then). */
function DueCell({ due, overdue, task }: {
  due: string | null; overdue: boolean;
  task?: Pick<ChangeTask, 'deadline_date' | 'deadline_kind' | 'urgent' | 'late' | 'escalation'>;
}) {
  if (!due) return <span className="text-slate-500">-</span>;
  const note = task ? dueNote(task) : null;
  return (
    <span data-testid="task-due" className="inline-flex flex-col items-start gap-0.5">
      <span className="inline-flex items-center gap-1">
        <DeadlineChip date={due} state={overdue ? 'overdue' : 'on_track'} />
        {task?.late && (
          <span data-testid="task-late" title={lateHint(task.escalation)}
            className="rounded bg-red-900/60 px-1.5 text-[11px] font-semibold text-red-200">
            {t('tasks.late')}
          </span>
        )}
      </span>
      <span className="text-[11px] tabular-nums text-slate-400">{formatCalendarDate(due)}</span>
      {note && <span data-testid="task-due-note" className="text-[11px] text-slate-500">{note}</span>}
    </span>
  );
}


const LetterChips = ({ letters }: { letters: string[] }) => (
  <span className="inline-flex gap-1 align-middle">
    {letters.map((l) => {
      const colors = rasicColors[l] ?? rasicColors['R'];
      return (
        <span key={l} data-testid="task-rasic"
          title={t(`rasic.${l}`)}
          className={`${colors.bg} ${colors.text} text-[11px] font-semibold px-1.5 py-px rounded`}>
          {l}
        </span>
      );
    })}
  </span>
);

type Row =
  | { source: 'change'; key: string; task: ChangeTask; overdue: boolean; due_date: string | null }
  | { source: 'workflow'; key: string; task: FoldedWorkflowTask; overdue: boolean; due_date: string | null };

/**
 * One list for everything owed: change tasks and workflow tasks, each job once
 * (R and A of the same department fold together), overdue first. The
 * department filter narrows the workflow rows; change tasks are always the
 * caller's own.
 */
function TaskList() {
  const navigate = useNavigate();
  const { data: departments = [], isLoading: loadingDepts } = useDepartments();
  const [selectedDeptId, setSelectedDeptId] = useState<number>(0);
  const { data: wfTasks, isLoading: loadingWf } = useMyTasks(selectedDeptId);
  const { data: changeTasks, isLoading: loadingChange } = useQuery({
    queryKey: ['change-my-tasks'],
    queryFn: () => changesApi.myTasks(),
    refetchInterval: 60_000,
  });
  const activeDepartments = departments.filter((d) => d.is_active);

  const allRows: Row[] = [
    ...foldChangeTasks(changeTasks).map((task): Row => ({
      source: 'change', key: `c-${task.kind}-${task.change_id}-${task.department_id ?? task.assessment_id ?? 0}`,
      task, overdue: task.overdue, due_date: task.due_date,
    })),
    ...foldWorkflowTasks(wfTasks).map((task): Row => ({
      source: 'workflow', key: `w-${task.task_id}`, task, overdue: task.overdue, due_date: task.due_date,
    })),
  ].sort((a, b) => mainFirst(
    { ...a, role: a.task.role }, { ...b, role: b.task.role }));
  // C3 "Needs you": decisions only this person gives, on top, by due.
  const needsYou = allRows.filter((r) => r.source === 'change' && r.task.needs_you && !isBackup(r.task))
    .sort((a, b) => (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999'));
  const rows = allRows.filter((r) => !needsYou.includes(r));
  // Project team (spec §18): the header counts main rows, the same number as
  // the sidebar badge; backup rows are listed after them, muted.
  const backupCount = rows.filter((r) => isBackup(r.task)).length;
  const mainCount = rows.length - backupCount;
  const head = (
    <thead>
      <tr className="border-b border-slate-700 bg-slate-900">
        <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.what')}</th>
        <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.task')}</th>
        <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.stage')}</th>
        <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.due')}</th>
        <th className="px-4 py-3" />
      </tr>
    </thead>
  );

  return (
    <div className="space-y-6">
      {needsYou.length > 0 && (
        <section data-testid="needs-you">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-amber-300">
            {t('tasks.needsYou')} ({needsYou.length})
          </h2>
          <div className="bg-slate-800 border border-amber-700/50 rounded-lg overflow-x-auto">
            <table className="w-full text-sm">
              {head}
              <tbody>
                {needsYou.map((row) => row.source === 'change'
                  && <ChangeTaskRow key={row.key} task={row.task} navigate={navigate} />)}
              </tbody>
            </table>
          </div>
        </section>
      )}
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3 mb-2">
        <h2 data-testid="task-list-title"
          className="text-sm font-semibold text-slate-300 uppercase tracking-wide">
          {t('tasks.openList')} ({mainCount})
          {backupCount > 0 && (
            <span data-testid="task-list-backup-count"
              className="ml-2 normal-case tracking-normal font-normal text-slate-500">
              {t('tasks.asBackup').replace('{n}', String(backupCount))}
            </span>
          )}
        </h2>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          {t('tasks.deptFilter')}
          {loadingDepts ? (
            <span className="inline-block h-7 w-40 bg-slate-700 rounded animate-pulse" />
          ) : (
            <select
              data-testid="task-dept-filter"
              value={selectedDeptId}
              onChange={(e) => setSelectedDeptId(Number(e.target.value))}
              className="bg-slate-700 border border-slate-600 text-slate-100 rounded-md px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value={0}>{t('tasks.myDepartments')}</option>
              {activeDepartments.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          )}
        </label>
      </div>

      {(loadingWf || loadingChange) && allRows.length === 0 ? (
        <LoadingSkeleton count={4} />
      ) : rows.length === 0 ? (needsYou.length > 0 ? null :
        <EmptyState data-testid="task-list-empty"
          title={selectedDeptId === 0 ? t('tasks.emptyMine') : t('tasks.emptyDept')} />)
      : (
        <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            {head}
            <tbody>
              {rows.map((row) => (row.source === 'change'
                ? <ChangeTaskRow key={row.key} task={row.task} navigate={navigate} />
                : <WorkflowTaskRow key={row.key} task={row.task} navigate={navigate} />))}
            </tbody>
          </table>
        </div>
      )}
    </div>
    </div>
  );
}

/** Mine rows carry a quiet tint; backup rows (spec §18) read muted. */
const rowClass = (task: { mine?: boolean; role?: string; late?: boolean }) =>
  `border-b border-slate-700 last:border-0 hover:bg-slate-700/30${
    task.mine ? ' bg-sky-950/30' : ''}${isBackup(task) && !task.late ? ' opacity-60' : ''}`;

/** The row's stage: the backend's label, else its stage key, else the change status. */
function taskStageLabel(task: Pick<ChangeTask, 'stage' | 'stage_label' | 'status'>): string {
  if (task.stage_label) return task.stage_label;
  const key = task.stage ?? task.status;
  if (!key) return '-';
  return STATUS_LABELS[key as keyof typeof STATUS_LABELS] ?? humanize(key);
}

function ChangeTaskRow({ task, navigate }: { task: ChangeTask; navigate: (to: string) => void }) {
  const hint = taskHint(task);
  const letters = task.rasic_letters ?? [];
  return (
    <tr data-testid="task-row" data-role={task.role ?? 'main'}
      className={rowClass(task)}>
      <td className="px-4 py-3 align-top">
        <span className="font-mono text-slate-100 whitespace-nowrap">{task.change_number}</span>
        <span className="block text-slate-200">{task.title}</span>
        {projectLabel(task.project_number, task.project_name) && (
          <span data-testid="task-project" className="block text-xs text-slate-400">
            {projectLabel(task.project_number, task.project_name)}
          </span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        {/* The department's task is mandatory: there is no accept step.
            A name appears once somebody has submitted. */}
        <span className="block">
          <span className="text-slate-200">{taskKindLabel(task.kind, task.kind_label)}</span>
          {letters.length > 0 && <span className="ml-2"><LetterChips letters={letters} /></span>}
          {task.kind === 'assessment' && task.owner_name && (
            <span data-testid="task-owner" className="block text-xs text-slate-400">
              {t('tasks.workingOn').replace('{x}', task.owner_name)}
            </span>
          )}
          {isBackup(task) && <BackupChip mainName={task.main_name} className="ml-2" />}
          {hint && <span className="block text-xs text-slate-400">{hint}</span>}
          {task.kind === 'obtain_info' && task.asking_side && (
            <span data-testid="task-asking-side" className="block text-xs text-slate-500">
              {t('tasks.hint.askedBy').replace('{x}', task.asking_side)}
            </span>
          )}
          {/* a customer question: the mail text, ready to copy (spec §0 [R4]) */}
          {task.kind === 'obtain_info' && task.customer_copy && (
            <span className="mt-1 block">
              <CustomerCopy text={task.customer_copy} testId={`task-copy-${task.change_id}`} />
            </span>
          )}
        </span>
      </td>
      <td data-testid="task-stage" className="px-4 py-3 align-top text-slate-300 whitespace-nowrap">
        {taskStageLabel(task)}
      </td>
      <td className="px-4 py-3 align-top text-xs"><DueCell due={task.due_date} overdue={task.overdue} task={task} /></td>
      <td className="px-4 py-3 align-top text-right">
        <button
          type="button"
          onClick={() => navigate(taskLink(task))}
          className={btnSm.primary}
        >
          {task.kind === 'assessment' && !task.checks_open ? 'Assess' : t('tasks.open')}
        </button>
      </td>
    </tr>
  );
}

function WorkflowTaskRow({ task, navigate }: { task: FoldedWorkflowTask; navigate: (to: string) => void }) {
  return (
    <tr data-testid="task-row" data-role={task.role ?? 'main'}
      className={rowClass(task)}>
      <td className="px-4 py-3 align-top">
        <span className="font-mono text-slate-100 whitespace-nowrap">{task.part_number}</span>
        <span className="block text-slate-200">{task.part_name}</span>
        <span className="block text-xs text-slate-400">{t('tasks.revision')} {task.revision_name}</span>
      </td>
      <td className="px-4 py-3 align-top">
        <span className="text-slate-200">{task.step_name}</span>
        <span className="ml-2"><LetterChips letters={task.letters} /></span>
        {/* Mandatory too: a name appears once somebody has worked the row. */}
        {task.owner_id !== null && task.owner_name && (
          <span className="block text-xs text-slate-400">{task.owner_name}</span>
        )}
        <span className="block text-xs text-slate-500">{task.department_name}</span>
        {isBackup(task) && <BackupChip mainName={task.main_name} className="mt-0.5" />}
      </td>
      <td className="px-4 py-3 align-top text-slate-300">
        <span className="whitespace-nowrap">{t('tasks.stageN').replace('{n}', String(task.stage_order))}</span>
        {task.stage_name && <span className="block text-xs text-slate-400">{task.stage_name}</span>}
      </td>
      <td className="px-4 py-3 align-top text-xs"><DueCell due={task.due_date} overdue={task.overdue} /></td>
      <td className="px-4 py-3 align-top text-right">
        <button
          type="button"
          onClick={() => navigate(`/projects/${task.project_id}`)}
          className={btnSm.secondary}
        >
          {t('tasks.viewPart')}
        </button>
      </td>
    </tr>
  );
}

/** The badge's number: every main row on this page, sections included. */
function MyTasksTotal() {
  const { total } = useMyTaskCounts();
  return (
    <span data-testid="my-tasks-total" className="text-slate-400 font-normal">({total})</span>
  );
}

export default function MyTasksPage() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
          My Tasks <MyTasksTotal />
        </h1>
        <p className="text-slate-400 text-sm mt-1">{t('tasks.subtitle')}</p>
      </div>

      <EscalationsCard />

      <TaskList />

      <IntakeSection />

      <CostSheetReviewTask />

      <SepItemsSection />

      <FormsSection />

      <LessonActionsSection />
    </div>
  );
}
