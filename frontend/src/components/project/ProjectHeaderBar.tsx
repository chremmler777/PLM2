/** Project page header. Task 7 turns it into the one-line header with status chips. */
import { useNavigate } from 'react-router-dom';
import MilestoneStrip from '../MilestoneStrip';
import StartChangeButton from '../changes/StartChangeButton';
import { CustomerNamingSelect } from './CustomerNamingSelect';
import type { Project } from './projectTypes';

export default function ProjectHeaderBar({ project, onStartChange, onAddPart }: {
  project: Project;
  onStartChange(): void;
  onAddPart(): void;
}) {
  const navigate = useNavigate();
  return (
    <div className="mb-6 flex items-center justify-between">
      <div>
        <button
          onClick={() => navigate('/projects')}
          className="text-sm text-blue-400 hover:text-blue-300 mb-3"
        >
          ← Back
        </button>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-100">
          {project.name} <span className="text-slate-400 text-sm">({project.code})</span>
        </h1>
        <div className="mt-2">
          <MilestoneStrip projectId={project.id} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <CustomerNamingSelect projectId={project.id} value={project.customer_naming ?? null} />
        <StartChangeButton label="Start change request"
          onClick={onStartChange}
          className="px-4 py-2 rounded bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
        <button
          onClick={onAddPart}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
        >
          + Add Part
        </button>
      </div>
    </div>
  );
}
