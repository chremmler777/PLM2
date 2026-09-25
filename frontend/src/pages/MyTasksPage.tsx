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
import { formatDate } from '../lib/format';
import { STATUS_LABELS } from '../lib/changeStatus';
import { humanize, taskKindLabel } from '../lib/humanLabels';
import { foldChangeTasks, foldWorkflowTasks, isBackup, mainFirst, type FoldedWorkflowTask } from '../lib/myTasks';
import BackupChip from '../components/common/BackupChip';
import client from '../api/client';
import { changesApi } from '../api/changes';
import { t } from '../i18n/cmLabels';
import type { ChangeTask } from '../types/change';
import { projectLabel } from '../lib/project';
import { toast } from 'sonner';
import FormPanel from '../forms/FormPanel';
import IntakeSection from '../components/intake/IntakeSection';
import CostSheetReviewTask from '../components/costSheet/CostSheetReviewTask';
import { useMyTaskCounts } from '../hooks/queries/useOpenTaskCount';

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;

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
      toast.success('Action completed');
      queryClient.invalidateQueries({ queryKey: ['my-lesson-actions'] });
    },
    onError: (error: unknown) => toast.error(errDetail(error) || 'Failed to complete'),
  });

  if (actions.length === 0) return null;

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">
        📘 Lesson Actions ({actions.length})
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
              <tr key={a.id} className="border-b border-slate-700 last:border-0 hover:bg-slate-750">
                <td className="px-4 py-3 text-slate-100">{a.description}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => navigate(`/lessons?lesson=${a.lesson_id}`)}
                    className="text-blue-400 hover:text-blue-300 underline text-left"
                  >
                    {a.lesson_title}
                  </button>
                  <span className="text-xs text-slate-500 ml-2">{a.lesson_status.replace(/_/g, ' ')}</span>
                </td>
                <td className="px-4 py-3 text-xs">
                  {a.due_date ? (
                    <span className={a.overdue ? 'text-red-400 font-semibold' : 'text-slate-400'}>
                      {formatDate(a.due_date)}{a.overdue && ' ⚠ overdue'}
                    </span>
                  ) : (
                    <span className="text-slate-500">-</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => complete.mutate(a.id)}
                    disabled={complete.isPending}
                    className="text-xs px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white"
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
    onError: (error: unknown) => toast.error(errDetail(error) || 'Failed to update'),
  });

  if (items.length === 0) return null;

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">
        🚦 SEP Work Packages ({items.length})
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
              <tr key={i.id} className="border-b border-slate-700 last:border-0 hover:bg-slate-750">
                <td className="px-4 py-3 text-slate-100">
                  {i.title_en}
                  <span className="text-xs text-slate-500 ml-2">{i.department}</span>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => navigate(`/projects/${i.project_id}`)}
                    className="text-blue-400 hover:text-blue-300 underline text-left"
                  >
                    {i.project_name}
                  </button>
                  <span className="text-xs text-slate-500 ml-2">{i.gate_code}</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  {formatDate(i.gate_target_date)}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => markDone.mutate(i.id)}
                    disabled={markDone.isPending}
                    className="text-xs px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white"
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
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">
        📝 SEP Forms ({forms.length})
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
                    className="text-blue-400 hover:text-blue-300 underline"
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


// Where each kind of change task is actually done, and how it reads in a list.
const TASK_TAB: Record<string, string> = {
  kickoff: '', scoping_wrapup: '?tab=scoping',
  impact_confirm: '?tab=impacted', customer_response: '',
  obtain_info: '?tab=scoping', close_question: '?tab=scoping',
  send_rejection: '?tab=scoping',
  costing_input: '?tab=commercial',
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
  validation_check: '?tab=implementation',
  update_quote: '?tab=implementation',
};

const kickoffHint = (missing?: string[]): string => {
  const parts = (missing ?? []).map((m) =>
    m === 'description' ? t('kickoff.description')
    : m === 'attachment' ? t('kickoff.attachment')
    : m === 'date' ? t('deadline.quote') : m);
  return parts.length === 0
    ? t('tasks.hint.kickoffReady')
    : t('tasks.hint.kickoff').replace('{x}', parts.join(', '));
};

const taskHint = (task: ChangeTask): string | null => {
  switch (task.kind) {
    case 'kickoff':
      return kickoffHint(task.missing);
    case 'scoping_wrapup': {
      const open = [
        ...(task.impact_confirmed ? [] : [t('tasks.hint.impactOpen')]),
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
    default:
      return null;
  }
};

/** The due cell: dd.mm.yyyy, red with a mark when overdue, "-" when undated. */
function DueCell({ due, overdue }: { due: string | null; overdue: boolean }) {
  if (!due) return <span className="text-slate-500">-</span>;
  return (
    <span className={`whitespace-nowrap ${overdue ? 'text-red-400 font-semibold' : 'text-slate-300'}`}>
      {formatDate(due)}
      {overdue && <span className="ml-1">⚠ {t('tasks.overdue')}</span>}
    </span>
  );
}

const LetterChips = ({ letters }: { letters: string[] }) => (
  <span className="inline-flex gap-1 align-middle">
    {letters.map((l) => {
      const colors = rasicColors[l] ?? rasicColors['R'];
      return (
        <span key={l} data-testid="task-rasic"
          className={`${colors.bg} ${colors.text} text-[10px] font-semibold px-1.5 py-0 rounded`}>
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

  const rows: Row[] = [
    ...foldChangeTasks(changeTasks).map((task): Row => ({
      source: 'change', key: `c-${task.kind}-${task.change_id}-${task.department_id ?? task.assessment_id ?? 0}`,
      task, overdue: task.overdue, due_date: task.due_date,
    })),
    ...foldWorkflowTasks(wfTasks).map((task): Row => ({
      source: 'workflow', key: `w-${task.task_id}`, task, overdue: task.overdue, due_date: task.due_date,
    })),
  ].sort((a, b) => mainFirst(
    { ...a, role: a.task.role }, { ...b, role: b.task.role }));
  // Project team (spec §18): the header counts main rows, the same number as
  // the sidebar badge; backup rows are listed after them, muted.
  const backupCount = rows.filter((r) => isBackup(r.task)).length;
  const mainCount = rows.length - backupCount;

  return (
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

      {(loadingWf || loadingChange) && rows.length === 0 ? (
        <LoadingSkeleton count={4} />
      ) : rows.length === 0 ? (
        <p data-testid="task-list-empty" className="rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-8 text-center text-sm text-slate-400">
          {selectedDeptId === 0 ? t('tasks.emptyMine') : t('tasks.emptyDept')}
        </p>
      ) : (
        <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-900">
                <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.what')}</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.task')}</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.stage')}</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.due')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (row.source === 'change'
                ? <ChangeTaskRow key={row.key} task={row.task} navigate={navigate} />
                : <WorkflowTaskRow key={row.key} task={row.task} navigate={navigate} />))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Mine rows carry the accent; backup rows (spec §18) read muted. */
const rowClass = (task: { mine?: boolean; role?: string }) =>
  `border-b border-slate-700 last:border-0 hover:bg-slate-750${
    task.mine ? ' border-l-2 border-sky-500' : ''}${isBackup(task) ? ' opacity-60' : ''}`;

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
            <span className="block text-xs text-slate-400">{task.owner_name}</span>
          )}
          {isBackup(task) && <BackupChip mainName={task.main_name} className="ml-2" />}
          {hint && <span className="block text-xs text-slate-400">{hint}</span>}
        </span>
      </td>
      <td data-testid="task-stage" className="px-4 py-3 align-top text-slate-300 whitespace-nowrap">
        {taskStageLabel(task)}
      </td>
      <td className="px-4 py-3 align-top text-xs"><DueCell due={task.due_date} overdue={task.overdue} /></td>
      <td className="px-4 py-3 align-top text-right">
        <button
          onClick={() => navigate(`/changes/${task.change_id}${TASK_TAB[task.kind] ?? ''}`)}
          className="text-xs px-3 py-1 rounded bg-blue-700 hover:bg-blue-600 text-white"
        >
          {task.kind === 'assessment' ? 'Assess' : t('tasks.open')}
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
          onClick={() => navigate(`/projects/${task.project_id}`)}
          className="text-xs px-3 py-1 rounded border border-slate-600 text-slate-200 hover:bg-slate-700 whitespace-nowrap"
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
