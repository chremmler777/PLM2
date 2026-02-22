/**
 * MyTasksPage - View active workflow tasks for a selected department
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDepartments, useMyTasks } from '../hooks/queries/useWorkflows';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { rasicColors } from '../lib/constants';

export default function MyTasksPage() {
  const navigate = useNavigate();
  const { data: departments = [], isLoading: loadingDepts } = useDepartments();
  const [selectedDeptId, setSelectedDeptId] = useState<number>(0);

  const { data: tasks = [], isLoading: loadingTasks } = useMyTasks(selectedDeptId);

  const activeDepartments = departments.filter((d) => d.is_active);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">My Tasks</h1>
        <p className="text-slate-400 text-sm mt-1">Active workflow tasks by department</p>
      </div>

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
            <option value={0}>— Select a department —</option>
            {activeDepartments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Task Table */}
      {selectedDeptId === 0 ? (
        <div className="text-center py-12 text-slate-400">
          Select a department to view its active tasks.
        </div>
      ) : loadingTasks ? (
        <LoadingSkeleton count={4} />
      ) : tasks.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-slate-400">No active tasks for this department.</p>
        </div>
      ) : (
        <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-900">
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Article</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Revision</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Step</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Stage</th>
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
                    className="border-b border-slate-700 hover:bg-slate-750 last:border-0"
                  >
                    <td className="px-4 py-3">
                      <div className="text-slate-100 font-medium">{task.article_name}</div>
                      <div className="text-slate-400 text-xs">{task.article_number}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-300">{task.revision_label}</td>
                    <td className="px-4 py-3 text-slate-300">{task.step_name}</td>
                    <td className="px-4 py-3 text-slate-300">
                      <span className="text-slate-400 text-xs mr-1">Stage {task.stage_order}</span>
                      {task.stage_name && (
                        <span className="text-slate-300">{task.stage_name}</span>
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
                        onClick={() => navigate(`/articles?highlight=${task.article_id}`)}
                        className="text-xs text-blue-400 hover:text-blue-300 underline"
                      >
                        View Article
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
