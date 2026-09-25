/**
 * StepEditorModal - Edit step details and RASIC assignments
 *
 * Retired departments are never offered for a new assignment; one the step
 * already carries stays readable (marked "retired") so an old template can be
 * cleaned up rather than silently rewritten.
 */

import { useId, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { Department } from '../../types/workflow';
import Dialog from '../common/Dialog';
import Button from '../common/Button';
import { btnIcon, btnSm } from '../common/buttonStyles';

const RASIC_LETTERS = ['R', 'A', 'S', 'C', 'I'];

/** One legend line per letter; the engine treats R and A as blocking. */
const RASIC_LEGEND: [string, string][] = [
  ['R', 'Responsible: does the work, blocking'],
  ['A', 'Accountable: final authority, blocking'],
  ['S', 'Supports: provides resources'],
  ['C', 'Consulted: asked for input, no answer owed'],
  ['I', 'Informed: kept in the loop'],
];

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

const fieldCls =
  'bg-slate-900 border border-slate-600 text-slate-100 rounded-lg text-sm focus:border-sky-500 focus:outline-none';

export default function StepEditorModal({ step, departments, onSave, onCancel }: Props) {
  const [stepName, setStepName] = useState(step.step_name);
  const [assignments, setAssignments] = useState(step.rasic_assignments);
  const nameId = useId();
  const nameRef = useRef<HTMLInputElement>(null);

  // Only active departments take new work; the API still returns retired rows.
  const active = departments.filter((d) => d.is_active !== false);
  const unassignedDepts = active.filter(
    (d) => !assignments.some((a) => a.department_id === d.id)
  );

  const handleAddAssignment = () => {
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

  const nameOf = (id: number) => departments.find((d) => d.id === id);

  return (
    <Dialog open onClose={onCancel} title="Edit step" size="lg" closeOnBackdrop={false}
      initialFocus={nameRef as React.RefObject<HTMLElement>}
      footer={(
        <>
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="primary" onClick={handleSave}>Save step</Button>
        </>
      )}>
      <div className="space-y-5">
        {/* Step Name */}
        <div>
          <label htmlFor={nameId} className="mb-1.5 block text-sm font-medium text-slate-200">
            Step name
          </label>
          <input
            id={nameId}
            ref={nameRef}
            type="text"
            value={stepName}
            onChange={(e) => setStepName(e.target.value)}
            className={`w-full px-3 py-2 ${fieldCls}`}
            placeholder="For example: Design review"
          />
        </div>

        {/* RASIC Assignments */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium text-slate-200">RASIC assignments</h3>
            <button
              type="button"
              onClick={handleAddAssignment}
              disabled={unassignedDepts.length === 0}
              className={btnSm.secondary}
            >
              <Plus aria-hidden="true" size={14} />
              Add department
            </button>
          </div>

          {assignments.length === 0 ? (
            <p className="text-xs text-slate-400">No departments on this step yet.</p>
          ) : (
            <ul className="space-y-2">
              {assignments.map((assignment, idx) => {
                const current = nameOf(assignment.department_id);
                const retired = current != null && current.is_active === false;
                const options = [
                  ...(current ? [current] : []),
                  ...unassignedDepts,
                ];
                return (
                  <li key={`${assignment.department_id}-${idx}`} className="flex items-center gap-2">
                    <select
                      aria-label={`Department ${idx + 1}`}
                      value={assignment.department_id}
                      onChange={(e) =>
                        handleAssignmentChange(idx, 'department_id', e.target.value)
                      }
                      className={`flex-1 px-2 py-1.5 ${fieldCls}`}
                    >
                      {options.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}{d.is_active === false ? ' (retired)' : ''}
                        </option>
                      ))}
                    </select>

                    <select
                      aria-label={`RASIC letter for ${current?.name ?? `department ${idx + 1}`}`}
                      value={assignment.rasic_letter}
                      onChange={(e) =>
                        handleAssignmentChange(idx, 'rasic_letter', e.target.value)
                      }
                      className={`w-16 px-2 py-1.5 ${fieldCls}`}
                    >
                      {RASIC_LETTERS.map((letter) => (
                        <option key={letter} value={letter}>
                          {letter}
                        </option>
                      ))}
                    </select>

                    <button
                      type="button"
                      aria-label={`Remove ${current?.name ?? 'department'} from this step`}
                      onClick={() => handleRemoveAssignment(idx)}
                      className={`${btnIcon} hover:text-red-300`}
                    >
                      <X aria-hidden="true" size={16} />
                    </button>
                    {retired && (
                      <span className="text-[11px] text-amber-300">Retired: pick an active department</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {unassignedDepts.length === 0 && assignments.length > 0 && (
            <p className="mt-2 text-xs text-slate-400">Every active department is on this step.</p>
          )}
        </div>

        {/* RASIC legend, after the controls it explains */}
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 rounded-lg border border-slate-700 bg-slate-900/60 p-3 text-xs text-slate-400 sm:grid-cols-2">
          {RASIC_LEGEND.map(([letter, meaning]) => (
            <div key={letter} className="flex gap-2">
              <dt className="w-3 font-semibold text-slate-200">{letter}</dt>
              <dd>{meaning}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Dialog>
  );
}
