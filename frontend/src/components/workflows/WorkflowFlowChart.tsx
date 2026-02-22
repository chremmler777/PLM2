/**
 * WorkflowFlowChart - Visual left-to-right flowchart of workflow stages and steps
 * Displays stages in columns with RASIC badges for each step
 * Supports viewing multiple versions with version history slider
 */

import { useState } from 'react';
import { WfTemplate } from '../../types/workflow';

interface VersionSnapshot {
  version: number;
  snapshot: {
    stages: Array<{
      stage_order: number;
      name: string | null;
      steps: Array<{
        step_name: string;
        position_in_stage: number;
        rasic: Array<{
          department_id: number;
          rasic_letter: string;
          department_name?: string;
        }>;
      }>;
    }>;
  };
  changed_at?: string;
  change_note?: string;
}

interface WorkflowFlowChartProps {
  template: Partial<WfTemplate>;
  versions?: VersionSnapshot[];
}

// RASIC color mapping
const rasicColors: Record<string, { bg: string; text: string }> = {
  R: { bg: 'bg-blue-900', text: 'text-blue-200' },
  A: { bg: 'bg-green-900', text: 'text-green-200' },
  S: { bg: 'bg-yellow-900', text: 'text-yellow-200' },
  I: { bg: 'bg-purple-900', text: 'text-purple-200' },
  C: { bg: 'bg-red-900', text: 'text-red-200' },
};

export default function WorkflowFlowChart({ template, versions = [] }: WorkflowFlowChartProps) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  // Debug logging
  console.log('WorkflowFlowChart rendered - versions.length:', versions?.length, 'versions:', versions);

  // Determine which version to display
  let displayedSnapshot: any = template.stages;
  let currentVersionInfo: VersionSnapshot | null = null;

  if (versions.length > 0) {
    if (selectedVersion === null) {
      // Default to latest version
      const latest = versions[versions.length - 1];
      displayedSnapshot = latest.snapshot.stages;
      currentVersionInfo = latest;
    } else {
      const found = versions.find((v: any) => v.version === selectedVersion);
      if (found) {
        displayedSnapshot = found.snapshot.stages;
        currentVersionInfo = found;
      }
    }
  }

  const stages = (displayedSnapshot || []).sort((a: any, b: any) => a.stage_order - b.stage_order);

  if (stages.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 bg-slate-800 border border-slate-700 rounded-lg">
        <p className="text-slate-400">No stages yet. Add stages to see the flowchart.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Version Selector (if history available) */}
      {versions.length >= 1 && (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-sm font-semibold text-slate-300">Template Version{versions.length > 1 ? 's' : ''}:</label>
            <div className="flex gap-2 flex-wrap">
              {versions.length === 0 ? (
                <span className="text-xs text-slate-500">No version history yet</span>
              ) : (
                versions.map((v: any) => (
                  <button
                    key={v.version}
                    onClick={() => setSelectedVersion(v.version)}
                    className={`px-3 py-1 rounded text-sm font-medium transition ${
                      selectedVersion === v.version || (selectedVersion === null && v === versions[versions.length - 1])
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                    }`}
                  >
                    v{v.version}
                  </button>
                ))
              )}
            </div>
            {currentVersionInfo && (
              <div className="text-xs text-slate-400 ml-auto">
                {currentVersionInfo.change_note && (
                  <span className="mr-2">• {currentVersionInfo.change_note}</span>
                )}
                {currentVersionInfo.changed_at && (
                  <span>{new Date(currentVersionInfo.changed_at).toLocaleDateString()}</span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Flowchart */}
      <div className="bg-slate-800 border border-slate-700 rounded-lg p-6 overflow-x-auto">
      <div className="flex gap-6 min-w-min pb-4">
        {stages.map((stage: any, idx: number) => (
          <div key={stage.stage_order} className="flex items-stretch gap-6">
            {/* Stage Column */}
            <div className="flex flex-col w-52 flex-shrink-0">
              {/* Stage Header */}
              <div className="bg-slate-700 text-slate-100 px-4 py-3 rounded-t-lg font-semibold text-sm border-b border-slate-600">
                <div className="text-xs text-slate-400 mb-1">Stage {stage.stage_order}</div>
                <div className="truncate">{stage.name || '(Unnamed)'}</div>
              </div>

              {/* Steps Body */}
              <div className="bg-slate-800 px-4 py-3 rounded-b-lg border border-t-0 border-slate-700 flex-1 space-y-2">
                {(!stage.steps || stage.steps.length === 0) ? (
                  <div className="text-xs text-slate-500 italic">No steps</div>
                ) : (
                  stage.steps
                    .sort((a: any, b: any) => a.position_in_stage - b.position_in_stage)
                    .map((step: any) => (
                      <div key={step.position_in_stage} className="bg-slate-700 px-3 py-2 rounded border border-slate-600">
                        <div className="text-xs font-semibold text-slate-100 mb-2 truncate">
                          ◈ {step.step_name}
                        </div>
                        {(!step.rasic || step.rasic.length === 0) ? (
                          <div className="text-xs text-slate-500">No assignments</div>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {step.rasic.map((rasic: any, idx: number) => {
                              const dept = rasic.department_name || 'Unknown';
                              const deptShort = dept.length > 8 ? dept.slice(0, 8) : dept;
                              const colors = rasicColors[rasic.rasic_letter] || rasicColors['R'];

                              return (
                                <div
                                  key={`${rasic.rasic_letter}-${rasic.department_id}-${idx}`}
                                  className={`${colors.bg} ${colors.text} text-xs px-2 py-1 rounded whitespace-nowrap`}
                                  title={`${rasic.rasic_letter}: ${dept}`}
                                >
                                  <span className="font-semibold">{rasic.rasic_letter}</span>
                                  <span className="ml-1 text-xs">{deptShort}</span>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    ))
                )}
              </div>
            </div>

            {/* Arrow Connector (not after last stage) */}
            {idx < stages.length - 1 && (
              <div className="flex items-center">
                <svg width="32" height="16" className="flex-shrink-0">
                  <line x1="0" y1="8" x2="24" y2="8" stroke="#64748b" strokeWidth="2" />
                  <polygon points="24,8 28,6 28,10" fill="#64748b" />
                </svg>
              </div>
            )}
          </div>
        ))}
      </div>

        {/* Legend */}
        <div className="mt-6 pt-6 border-t border-slate-700">
          <div className="text-xs font-semibold text-slate-300 mb-3">RASIC Legend:</div>
          <div className="grid grid-cols-5 gap-2 text-xs">
            <div>
              <div className={`${rasicColors.R.bg} ${rasicColors.R.text} px-2 py-1 rounded mb-1 font-semibold`}>R</div>
              <div className="text-slate-400">Responsible</div>
            </div>
            <div>
              <div className={`${rasicColors.A.bg} ${rasicColors.A.text} px-2 py-1 rounded mb-1 font-semibold`}>A</div>
              <div className="text-slate-400">Accountable</div>
            </div>
            <div>
              <div className={`${rasicColors.S.bg} ${rasicColors.S.text} px-2 py-1 rounded mb-1 font-semibold`}>S</div>
              <div className="text-slate-400">Supportive</div>
            </div>
            <div>
              <div className={`${rasicColors.I.bg} ${rasicColors.I.text} px-2 py-1 rounded mb-1 font-semibold`}>I</div>
              <div className="text-slate-400">Informed</div>
            </div>
            <div>
              <div className={`${rasicColors.C.bg} ${rasicColors.C.text} px-2 py-1 rounded mb-1 font-semibold`}>C</div>
              <div className="text-slate-400">Consulted</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
