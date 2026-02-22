/**
 * WorkflowDesignerPage - Visual workflow template designer
 */

import { useState } from 'react';
import { useTemplates, useDepartments, useCreateTemplate, useUpdateTemplate, useDeactivateTemplate } from '../hooks/queries/useWorkflows';
import { WfTemplate, WfTemplateSave, WfStep, Department } from '../types/workflow';
import * as workflowApi from '../api/workflows';
import { toast } from 'sonner';
import StepEditorModal from '../components/workflows/StepEditorModal';
import WorkflowFlowChart from '../components/workflows/WorkflowFlowChart';

export default function WorkflowDesignerPage() {
  const { data: templates, isLoading: templatesLoading } = useTemplates();
  const { data: departments } = useDepartments();
  const createMutation = useCreateTemplate();
  const deactivateMutation = useDeactivateTemplate();

  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<number | null>(null);

  // Local editor state
  const [editorTemplate, setEditorTemplate] = useState<Partial<WfTemplate> | null>(null);
  const [viewMode, setViewMode] = useState<'edit' | 'flowchart'>('edit');
  const [versionHistory, setVersionHistory] = useState<any[]>([]);

  // Step editor modal state
  const [editingStage, setEditingStage] = useState<number | null>(null);
  const [editingStep, setEditingStep] = useState<WfStep | null>(null);

  const selectedTemplate = selectedTemplateId && templates ? templates.find((t: any) => t.id === selectedTemplateId) : null;
  const updateMutation = useUpdateTemplate(selectedTemplateId || 0);

  // Handle new template
  const handleNewTemplate = () => {
    setEditorTemplate({
      name: 'Untitled Workflow',
      description: '',
      stages: [],
    });
    setSelectedTemplateId(null);
    setSelectedStepId(null);
    setViewMode('edit');
    setVersionHistory([]);
  };

  // Handle edit - fetch full template data and version history
  const handleEditTemplate = async (templateId: number) => {
    try {
      const fullTemplate = await workflowApi.getTemplate(templateId);
      setSelectedTemplateId(templateId);
      setEditorTemplate({
        name: fullTemplate.name,
        description: fullTemplate.description,
        stages: JSON.parse(JSON.stringify(fullTemplate.stages)), // Deep copy
      });
      setSelectedStepId(null);

      // Fetch version history
      try {
        console.log('Attempting to fetch version history for template:', templateId);
        const history = await workflowApi.getTemplateHistory(templateId);
        console.log('✓ Fetched version history:', history, 'Count:', history?.length);
        setVersionHistory(history || []);
      } catch (historyError: any) {
        console.error('✗ Could not fetch version history:', historyError);
        console.error('Error details:', historyError?.response?.status, historyError?.response?.data);
        setVersionHistory([]);
      }
    } catch (error) {
      toast.error('Failed to load template');
    }
  };

  // Handle save
  const handleSave = async () => {
    if (!editorTemplate || !editorTemplate.name) {
      toast.error('Template name is required');
      return;
    }

    if (!editorTemplate.stages || editorTemplate.stages.length === 0) {
      toast.error('Add at least one stage');
      return;
    }

    const saveData: WfTemplateSave = {
      name: editorTemplate.name,
      description: editorTemplate.description || null,
      stages: (editorTemplate.stages || []).map((stage: any) => ({
        stage_order: stage.stage_order,
        name: stage.name,
        steps: (stage.steps || []).map((step: any) => ({
          step_name: step.step_name,
          position_in_stage: step.position_in_stage,
          rasic_assignments: (step.rasic_assignments || []).map((rasic: any) => ({
            department_id: rasic.department_id,
            rasic_letter: rasic.rasic_letter,
          })),
        })),
      })),
      change_note: selectedTemplate ? 'Updated' : undefined,
    };

    try {
      if (selectedTemplate) {
        await updateMutation.mutateAsync(saveData);
        toast.success('Template updated');
      } else {
        const created = await createMutation.mutateAsync(saveData);
        toast.success('Template created');
        setSelectedTemplateId(created.id);
      }
      setEditorTemplate(null);
      setSelectedStepId(null);
    } catch (error: any) {
      console.error('Save error:', error);
      const errorMsg = error?.response?.data?.detail || error?.message || 'Failed to save template';
      toast.error(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg));
    }
  };

  // Handle cancel
  const handleCancel = () => {
    setEditorTemplate(null);
    setSelectedTemplateId(null);
    setSelectedStepId(null);
    setViewMode('edit');
    setVersionHistory([]);
  };

  // Handle add stage
  const handleAddStage = () => {
    if (!editorTemplate) return;
    const newStages = [...(editorTemplate.stages || [])];
    const maxOrder = newStages.length > 0 ? Math.max(...newStages.map((s: any) => s.stage_order)) : 0;
    newStages.push({
      stage_order: maxOrder + 1,
      name: null,
      steps: [],
    });
    setEditorTemplate({ ...editorTemplate, stages: newStages });
  };

  // Handle delete stage
  const handleDeleteStage = (stageOrder: number) => {
    if (!editorTemplate) return;
    const newStages = (editorTemplate.stages || []).filter((s: any) => s.stage_order !== stageOrder);
    setEditorTemplate({ ...editorTemplate, stages: newStages });
  };

  // Handle add step
  const handleAddStep = (stageOrder: number) => {
    if (!editorTemplate) return;
    const stage = editorTemplate.stages?.find((s: any) => s.stage_order === stageOrder);
    if (!stage) return;

    const maxPos = stage.steps?.length > 0 ? Math.max(...stage.steps.map((s: any) => s.position_in_stage)) : 0;
    const newStep = {
      step_name: 'New Step',
      position_in_stage: maxPos + 1,
      rasic_assignments: [],
    };

    setEditingStage(stageOrder);
    setEditingStep(newStep);
  };

  // Handle save step from modal
  const handleSaveStep = (updatedStep: WfStep) => {
    if (!editorTemplate || !editingStage) return;

    const newStages = (editorTemplate.stages || []).map((stage: any) => {
      if (stage.stage_order === editingStage) {
        // Check if this is a new step or updating existing
        const existingStepIdx = stage.steps?.findIndex(
          (s: any) => s.position_in_stage === updatedStep.position_in_stage
        );

        if (existingStepIdx >= 0) {
          // Update existing
          const newSteps = [...stage.steps];
          newSteps[existingStepIdx] = updatedStep;
          return { ...stage, steps: newSteps };
        } else {
          // Add new
          return { ...stage, steps: [...(stage.steps || []), updatedStep] };
        }
      }
      return stage;
    });

    setEditorTemplate({ ...editorTemplate, stages: newStages });
    setEditingStage(null);
    setEditingStep(null);
  };

  // Handle delete step
  const handleDeleteStep = (stageOrder: number, position: number) => {
    if (!editorTemplate) return;
    const newStages = (editorTemplate.stages || []).map((stage: any) => {
      if (stage.stage_order === stageOrder) {
        return {
          ...stage,
          steps: stage.steps.filter((s: any) => s.position_in_stage !== position),
        };
      }
      return stage;
    });
    setEditorTemplate({ ...editorTemplate, stages: newStages });
  };

  // Handle deactivate
  const handleDeactivate = async (templateId: number) => {
    if (!confirm('Deactivate this template?')) return;
    try {
      await deactivateMutation.mutateAsync(templateId);
      toast.success('Template deactivated');
      if (selectedTemplateId === templateId) {
        setSelectedTemplateId(null);
        setEditorTemplate(null);
      }
    } catch (error) {
      toast.error('Failed to deactivate');
    }
  };

  if (templatesLoading) {
    return <div className="p-8 text-slate-400">Loading...</div>;
  }

  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold text-slate-100 mb-2">Workflow Template Designer</h1>

        {/* Info Box */}
        <div className="mb-6 p-4 bg-blue-900 border border-blue-700 rounded-lg text-sm text-blue-100">
          <p className="font-semibold mb-2">📋 How it works:</p>
          <ul className="space-y-1 text-xs">
            <li>• <span className="font-semibold">Stages</span> are serial (one after another)</li>
            <li>• <span className="font-semibold">Steps within a stage</span> are parallel (can run simultaneously)</li>
            <li>• Each step can be assigned to multiple departments with RASIC roles</li>
          </ul>
        </div>

        <div className="flex gap-8">
          {/* Left sidebar: Template list */}
          <div className="w-64 flex-shrink-0">
            <button
              onClick={handleNewTemplate}
              className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 mb-4 font-medium"
            >
              + New Template
            </button>

            <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
              <h2 className="text-lg font-bold text-slate-100 mb-4">Templates</h2>
              <div className="space-y-2 max-h-[600px] overflow-y-auto">
                {!templates || templates.length === 0 ? (
                  <p className="text-slate-400 text-sm">No templates yet</p>
                ) : (
                  templates.map((template) => (
                    <div
                      key={template.id}
                      className={`p-3 rounded-lg cursor-pointer transition ${
                        selectedTemplateId === template.id
                          ? 'bg-blue-900 border border-blue-400'
                          : 'bg-slate-700 border border-slate-600 hover:bg-slate-600'
                      }`}
                    >
                      <button
                        onClick={() => handleEditTemplate(template.id)}
                        className="w-full text-left"
                      >
                        <div className="font-semibold text-slate-100">{template.name}</div>
                        <div className="text-xs text-slate-400 mt-1">v{template.version}</div>
                      </button>
                      {selectedTemplateId === template.id && (
                        <button
                          onClick={() => handleDeactivate(template.id)}
                          className="text-xs text-red-400 hover:text-red-300 mt-2"
                        >
                          Deactivate
                        </button>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Main editor area */}
          <div className="flex-1">
            {!editorTemplate ? (
              <div className="bg-slate-800 rounded-lg border border-slate-700 p-8 text-center">
                <p className="text-slate-400">Select a template or create a new one</p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Header */}
                <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
                  <input
                    type="text"
                    value={editorTemplate.name || ''}
                    onChange={(e) => setEditorTemplate({ ...editorTemplate, name: e.target.value })}
                    className="w-full px-4 py-2 bg-slate-900 border border-slate-600 text-slate-100 rounded-lg mb-2 text-2xl font-bold"
                    placeholder="Template name"
                  />
                  <textarea
                    value={editorTemplate.description || ''}
                    onChange={(e) => setEditorTemplate({ ...editorTemplate, description: e.target.value })}
                    className="w-full px-4 py-2 bg-slate-900 border border-slate-600 text-slate-100 rounded-lg text-sm"
                    placeholder="Description..."
                    rows={2}
                  />
                  {selectedTemplate && (
                    <div className="text-xs text-slate-400 mt-3">
                      v{selectedTemplate.version} • Updated {selectedTemplate.updated_at ? new Date(selectedTemplate.updated_at).toLocaleDateString() : 'never'}
                    </div>
                  )}
                </div>

                {/* View Mode Toggle */}
                <div className="flex gap-2 bg-slate-800 border border-slate-700 rounded-lg p-1 w-fit">
                  <button
                    onClick={() => setViewMode('edit')}
                    className={`px-4 py-2 rounded font-medium transition ${
                      viewMode === 'edit'
                        ? 'bg-slate-600 text-slate-100'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => setViewMode('flowchart')}
                    className={`px-4 py-2 rounded font-medium transition ${
                      viewMode === 'flowchart'
                        ? 'bg-slate-600 text-slate-100'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Flowchart
                  </button>
                </div>

                {/* Edit Mode: Stages */}
                {viewMode === 'edit' && (
                <div className="space-y-4">
                  {(!editorTemplate.stages || editorTemplate.stages.length === 0) && (
                    <div className="text-center py-8 text-slate-400">
                      <p className="mb-4">No stages yet. Add one to get started.</p>
                      <button
                        onClick={handleAddStage}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                      >
                        + Add Stage
                      </button>
                    </div>
                  )}

                  {(editorTemplate.stages || []).map((stage: any, idx: number) => (
                    <StageEditor
                      key={stage.stage_order}
                      stage={stage}
                      departments={departments || []}
                      selectedStepId={selectedStepId}
                      onSelectStep={setSelectedStepId}
                      onEditStep={(step) => {
                        setEditingStage(stage.stage_order);
                        setEditingStep(step);
                      }}
                      onAddStep={() => handleAddStep(stage.stage_order)}
                      onDeleteStep={(pos) => handleDeleteStep(stage.stage_order, pos)}
                      onDeleteStage={() => handleDeleteStage(stage.stage_order)}
                      onUpdateStage={(updated) => {
                        const newStages = (editorTemplate.stages || []).map((s: any) =>
                          s.stage_order === stage.stage_order ? updated : s
                        );
                        setEditorTemplate({ ...editorTemplate, stages: newStages });
                      }}
                    />
                  ))}

                  {editorTemplate.stages && editorTemplate.stages.length > 0 && (
                    <button
                      onClick={handleAddStage}
                      className="w-full px-4 py-3 bg-slate-700 text-slate-200 rounded-lg hover:bg-slate-600 text-center"
                    >
                      + Add Stage
                    </button>
                  )}
                </div>
                )}

                {/* Flowchart Mode: Visual Preview */}
                {viewMode === 'flowchart' && (
                  <WorkflowFlowChart template={editorTemplate} versions={versionHistory} />
                )}

                {/* Actions */}
                <div className="flex gap-3 justify-end pt-4 border-t border-slate-700">
                  <button
                    onClick={handleCancel}
                    className="px-6 py-2 bg-slate-700 text-slate-100 rounded-lg hover:bg-slate-600 font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={createMutation.isPending || updateMutation.isPending}
                    className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-slate-600 font-medium"
                  >
                    {createMutation.isPending || updateMutation.isPending ? 'Saving...' : 'Save'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Step Editor Modal */}
      {editingStep && (
        <StepEditorModal
          step={editingStep}
          departments={departments || []}
          onSave={handleSaveStep}
          onCancel={() => {
            setEditingStage(null);
            setEditingStep(null);
          }}
        />
      )}
    </div>
  );
}

// Stage editor component
function StageEditor({ stage, departments, selectedStepId, onSelectStep, onEditStep, onAddStep, onDeleteStep, onDeleteStage, onUpdateStage }: any) {
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-slate-400">Stage {stage.stage_order}</span>
          <input
            type="text"
            value={stage.name || ''}
            onChange={(e) => onUpdateStage({ ...stage, name: e.target.value })}
            className="px-3 py-1 bg-slate-900 border border-slate-600 text-slate-100 rounded text-sm max-w-xs"
            placeholder="Stage name (optional)"
          />
        </div>
        <button
          onClick={onDeleteStage}
          className="px-2 py-1 text-red-400 hover:text-red-300 text-sm"
        >
          Delete
        </button>
      </div>

      {stage.steps && stage.steps.length > 0 ? (
        <div className="space-y-3">
          {stage.steps.map((step: any) => (
            <StepCard
              key={step.position_in_stage}
              step={step}
              isSelected={selectedStepId === step.position_in_stage}
              departments={departments}
              onEdit={() => onEditStep(step)}
              onDelete={() => onDeleteStep(step.position_in_stage)}
            />
          ))}
        </div>
      ) : (
        <p className="text-slate-400 text-sm mb-3">No steps in this stage</p>
      )}

      <button
        onClick={onAddStep}
        className="w-full mt-4 px-3 py-2 bg-slate-700 text-slate-200 rounded hover:bg-slate-600 text-sm"
      >
        + Add Step
      </button>
    </div>
  );
}

// Step card component
function StepCard({ step, isSelected, departments, onEdit, onDelete }: any) {
  const rasicLetters = step.rasic_assignments.map((r: any) => r.rasic_letter).join('');
  const deptNames = step.rasic_assignments
    .map((r: any) => departments.find((d: Department) => d.id === r.department_id)?.name)
    .filter(Boolean)
    .join(', ');

  return (
    <div
      onClick={onEdit}
      className="p-3 rounded border cursor-pointer transition bg-slate-700 border-slate-600 hover:bg-slate-600"
    >
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <div className="font-semibold text-slate-100">{step.step_name}</div>
          {rasicLetters ? (
            <div className="text-xs text-slate-400 mt-1">
              RASIC: {rasicLetters} • {deptNames}
            </div>
          ) : (
            <div className="text-xs text-slate-500 mt-1">No RASIC assignments yet</div>
          )}
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="px-2 py-1 text-red-400 hover:text-red-300 text-sm"
        >
          ×
        </button>
      </div>
    </div>
  );
}
