/**
 * MyTasksPage - View active workflow tasks for a selected department
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useDepartments, useMyTasks, useAcceptTask } from '../hooks/queries/useWorkflows';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import EscalationsCard from '../components/EscalationsCard';
import { rasicColors } from '../lib/constants';
import client from '../api/client';
import { changesApi } from '../api/changes';
import { t } from '../i18n/cmLabels';
import { toast } from 'sonner';

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
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to complete'),
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
                      {a.due_date.slice(0, 10)}{a.overdue && ' ⚠ overdue'}
                    </span>
                  ) : (
                    <span className="text-slate-500">—</span>
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
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to update'),
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
                  {i.gate_target_date ? i.gate_target_date.slice(0, 10) : '—'}
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

function ChangeTasksSection() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: tasks = [] } = useQuery({
    queryKey: ['change-my-tasks'],
    queryFn: () => changesApi.myTasks(),
    refetchInterval: 60_000,
  });

  const accept = useMutation({
    mutationFn: ({ changeId, assessmentId }: { changeId: number; assessmentId: number }) =>
      changesApi.acceptAssessment(changeId, assessmentId),
    onSuccess: () => {
      toast.success('Assessment accepted');
      queryClient.invalidateQueries({ queryKey: ['change-my-tasks'] });
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to accept'),
  });

  if (tasks.length === 0) return null;

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-2">
        🔄 Change Assessments ({tasks.length})
      </h2>
      <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 bg-slate-900">
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Change</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">Title</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.owner')}</th>
              <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.due')}</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr
                key={`${task.change_id}-${task.assessment_id}`}
                className={`border-b border-slate-700 last:border-0 hover:bg-slate-750${
                  task.mine ? ' border-l-2 border-sky-500' : ''
                }`}
              >
                <td className="px-4 py-3">
                  <span className="font-mono text-slate-100">{task.change_number}</span>
                </td>
                <td className="px-4 py-3 text-slate-100">{task.title}</td>
                <td className="px-4 py-3">
                  {task.owner_id !== null ? (
                    <span className="text-slate-200">{task.owner_name}</span>
                  ) : (
                    <button
                      onClick={() =>
                        accept.mutate({ changeId: task.change_id, assessmentId: task.assessment_id })
                      }
                      disabled={accept.isPending}
                      className="px-2 py-0.5 rounded bg-sky-700 hover:bg-sky-600 text-sky-100 text-xs"
                    >
                      {t('tasks.accept')}
                    </button>
                  )}
                </td>
                <td className="px-4 py-3 text-xs">
                  {task.due_date ? (
                    <span className={task.overdue ? 'text-red-400 font-semibold' : 'text-slate-300'}>
                      {new Date(task.due_date).toLocaleDateString()}
                      {task.overdue && <span className="ml-1">⚠ {t('tasks.overdue')}</span>}
                    </span>
                  ) : (
                    <span className="text-slate-500">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => navigate(`/changes/${task.change_id}`)}
                    className="text-xs px-3 py-1 rounded bg-blue-700 hover:bg-blue-600 text-white"
                  >
                    Assess
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

export default function MyTasksPage() {
  const navigate = useNavigate();
  const { data: departments = [], isLoading: loadingDepts } = useDepartments();
  const [selectedDeptId, setSelectedDeptId] = useState<number>(0);

  const { data: tasks = [], isLoading: loadingTasks } = useMyTasks(selectedDeptId);
  const acceptTask = useAcceptTask();

  const activeDepartments = departments.filter((d) => d.is_active);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">My Tasks</h1>
        <p className="text-slate-400 text-sm mt-1">Active workflow tasks by department</p>
      </div>

      <EscalationsCard />

      <SepItemsSection />

      <ChangeTasksSection />

      <LessonActionsSection />

      {/* Department Selector */}
      <div className="max-w-xs">
        <label className="block text-sm font-medium text-slate-300 mb-2">Department</label>
        {loadingDepts ? (
          <div className="h-9 bg-slate-700 rounded animate-pulse" />
        ) : (
          <select
            value={selectedDeptId}
            onChange={(e) => setSelectedDeptId(Number(e.target.value))}
            className="w-full bg-slate-700 border border-slate-600 text-slate-100 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={0}>My departments</option>
            {activeDepartments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Task Table */}
      {loadingTasks ? (
        <LoadingSkeleton count={4} />
      ) : tasks.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-slate-400">
            {selectedDeptId === 0
              ? 'No active tasks in your departments — ask an admin to assign you to departments if this looks wrong.'
              : 'No active tasks for this department.'}
          </p>
        </div>
      ) : (
        <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-900">
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Part</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Revision</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Step</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Stage</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.owner')}</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">{t('tasks.due')}</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">RASIC</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Started</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => {
                const colors = rasicColors[task.rasic_letter] ?? rasicColors['R'];
                const startedDate = new Date(task.instance_started_at).toLocaleDateString();
                return (
                  <tr
                    key={task.task_id}
                    className={`border-b border-slate-700 hover:bg-slate-750 last:border-0${
                      task.mine ? ' border-l-2 border-sky-500' : ''
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="text-slate-100 font-medium">{task.part_name}</div>
                      <div className="text-slate-400 text-xs">{task.part_number}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-300">{task.revision_name}</td>
                    <td className="px-4 py-3 text-slate-300">{task.step_name}</td>
                    <td className="px-4 py-3 text-slate-300">
                      <span className="text-slate-400 text-xs mr-1">Stage {task.stage_order}</span>
                      {task.stage_name && (
                        <span className="text-slate-300">{task.stage_name}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {task.owner_id !== null ? (
                        <span className="text-slate-200">{task.owner_name}</span>
                      ) : (
                        <button
                          onClick={() =>
                            acceptTask.mutate({ instanceId: task.instance_id, taskId: task.task_id })
                          }
                          disabled={acceptTask.isPending}
                          className="px-2 py-0.5 rounded bg-sky-700 hover:bg-sky-600 text-sky-100 text-xs"
                        >
                          {t('tasks.accept')}
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {task.due_date ? (
                        <span className={task.overdue ? 'text-red-400 font-semibold' : 'text-slate-300'}>
                          {new Date(task.due_date).toLocaleDateString()}
                          {task.overdue && <span className="ml-1">⚠ {t('tasks.overdue')}</span>}
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`${colors.bg} ${colors.text} text-xs font-semibold px-2 py-0.5 rounded`}
                      >
                        {task.rasic_letter}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{startedDate}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => navigate(`/projects/${task.project_id}`)}
                        className="text-xs text-blue-400 hover:text-blue-300 underline"
                      >
                        View Part
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
