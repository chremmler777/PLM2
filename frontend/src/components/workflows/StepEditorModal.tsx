/**
 * StepEditorModal - Edit step details and RASIC assignments
 */

import { useState } from 'react';
import { Department } from '../../types/workflow';

const RASIC_LETTERS = ['R', 'A', 'S', 'I', 'C'];

interface StepData {
  step_name: string;
  position_in_stage: number;
  rasic_assignments: Array<{
    department_id: number;
    rasic_letter: string;
  }>;
}

interface Props {
  step: StepData;
  departments: Department[];
  onSave: (step: StepData) => void;
  onCancel: () => void;
}

export default function StepEditorModal({ step, departments, onSave, onCancel }: Props) {
  const [stepName, setStepName] = useState(step.step_name);
  const [assignments, setAssignments] = useState(step.rasic_assignments);

  const handleAddAssignment = () => {
    const unassignedDepts = departments.filter(
      (d) => !assignments.some((a) => a.department_id === d.id)
    );
    if (unassignedDepts.length > 0) {
      setAssignments([
        ...assignments,
        {
          department_id: unassignedDepts[0].id,
          rasic_letter: 'R',
        },
      ]);
    }
  };

  const handleRemoveAssignment = (index: number) => {
    setAssignments(assignments.filter((_, i) => i !== index));
  };

  const handleAssignmentChange = (
    index: number,
    field: 'department_id' | 'rasic_letter',
    value: string | number
  ) => {
    const updated = [...assignments];
    updated[index] = {
      ...updated[index],
      [field]: field === 'department_id' ? parseInt(value as string) : value,
    };
    setAssignments(updated);
  };

  const handleSave = () => {
    onSave({
      ...step,
      step_name: stepName,
      rasic_assignments: assignments,
    });
  };

  const unassignedDepts = departments.filter(
    (d) => !assignments.some((a) => a.department_id === d.id)
  );

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <h2 className="text-xl font-bold text-slate-100 mb-4">Edit Step</h2>

        {/* RASIC Legend */}
        <div className="mb-6 p-4 bg-slate-900 border border-slate-700 rounded-lg">
          <p className="text-xs font-semibold text-slate-300 mb-2">RASIC Matrix Legend:</p>
          <div className="grid grid-cols-2 gap-2 text-xs text-slate-400">
            <div><span className="font-bold text-blue-400">R</span> - Responsible (does the work)</div>
            <div><span className="font-bold text-green-400">A</span> - Accountable (final authority)</div>
            <div><span className="font-bold text-yellow-400">S</span> - Supportive (provides resources)</div>
            <div><span className="font-bold text-purple-400">I</span> - Informed (kept in the loop)</div>
            <div><span className="font-bold text-red-400">C</span> - Consulted (asked for input)</div>
          </div>
        </div>

        {/* Step Name */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-slate-200 mb-2">
            Step Name
          </label>
          <input
            type="text"
            value={stepName}
            onChange={(e) => setStepName(e.target.value)}
            className="w-full px-3 py-2 bg-slate-900 border border-slate-600 text-slate-100 rounded-lg focus:border-blue-500 focus:outline-none"
            placeholder="e.g., Design Review"
          />
        </div>

        {/* RASIC Assignments */}
        <div className="mb-6">
          <div className="flex justify-between items-center mb-3">
            <label className="block text-sm font-medium text-slate-200">
              RASIC Assignments
            </label>
            <button
              onClick={handleAddAssignment}
              disabled={unassignedDepts.length === 0}
              className="text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-slate-600 disabled:cursor-not-allowed"
            >
              + Add
            </button>
          </div>

          {assignments.length === 0 ? (
            <p className="text-xs text-slate-400 mb-3">No assignments yet</p>
          ) : (
            <div className="space-y-2 mb-3">
              {assignments.map((assignment, idx) => {
                const dept = departments.find((d) => d.id === assignment.department_id);
                return (
                  <div key={idx} className="flex gap-2 items-center">
                    <select
                      value={assignment.department_id}
                      onChange={(e) =>
                        handleAssignmentChange(idx, 'department_id', e.target.value)
                      }
                      className="flex-1 px-2 py-1 bg-slate-900 border border-slate-600 text-slate-100 rounded text-sm focus:border-blue-500 focus:outline-none"
                    >
                      {[
                        departments.find((d) => d.id === assignment.department_id),
                        ...unassignedDepts,
                      ]
                        .filter(Boolean)
                        .map((d) => (
                          <option key={d?.id} value={d?.id}>
                            {d?.name}
                          </option>
                        ))}
                    </select>

                    <select
                      value={assignment.rasic_letter}
                      onChange={(e) =>
                        handleAssignmentChange(idx, 'rasic_letter', e.target.value)
                      }
                      className="w-16 px-2 py-1 bg-slate-900 border border-slate-600 text-slate-100 rounded text-sm focus:border-blue-500 focus:outline-none"
                    >
                      {RASIC_LETTERS.map((letter) => (
                        <option key={letter} value={letter}>
                          {letter}
                        </option>
                      ))}
                    </select>

                    <button
                      onClick={() => handleRemoveAssignment(idx)}
                      className="px-2 py-1 text-red-400 hover:text-red-300 text-sm"
                    >
                      ×
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {unassignedDepts.length === 0 && assignments.length > 0 && (
            <p className="text-xs text-slate-400">All departments assigned</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 bg-slate-700 text-slate-100 rounded hover:bg-slate-600 text-sm font-medium"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
