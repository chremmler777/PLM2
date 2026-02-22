/**
 * Workflow API functions
 */
import client from './client';
import {
  Department, WfTemplate, WfTemplateList, WfTemplateSave,
  WfInstance, MyTask,
  StartWorkflowRequest, CompleteTaskRequest, CancelWorkflowRequest,
} from '../types/workflow';

export const getDepartments = async (): Promise<Department[]> => {
  const response = await client.get('/v1/workflow-templates/departments');
  return response.data;
};

export const listTemplates = async (): Promise<WfTemplateList[]> => {
  const response = await client.get('/v1/workflow-templates');
  return response.data;
};

export const getTemplate = async (templateId: number): Promise<WfTemplate> => {
  const response = await client.get(`/v1/workflow-templates/${templateId}`);
  return response.data;
};

export const getTemplateHistory = async (templateId: number): Promise<any[]> => {
  const response = await client.get(`/v1/workflow-templates/${templateId}/history`);
  return response.data;
};

export const createTemplate = async (data: WfTemplateSave): Promise<WfTemplate> => {
  const response = await client.post('/v1/workflow-templates', data);
  return response.data;
};

export const updateTemplate = async (templateId: number, data: WfTemplateSave): Promise<WfTemplate> => {
  const response = await client.put(`/v1/workflow-templates/${templateId}`, data);
  return response.data;
};

export const deactivateTemplate = async (templateId: number): Promise<void> => {
  await client.delete(`/v1/workflow-templates/${templateId}`);
};

// ============================================================================
// Phase 3c: Workflow instance API functions
// ============================================================================

export const startWorkflow = async (
  revisionId: number,
  data: StartWorkflowRequest,
): Promise<WfInstance> => {
  const response = await client.post(`/v1/workflow-instances/revisions/${revisionId}/start`, data);
  return response.data;
};

export const getRevisionWorkflow = async (
  revisionId: number,
): Promise<WfInstance | null> => {
  const response = await client.get(`/v1/workflow-instances/revisions/${revisionId}/current`);
  return response.data.instance;
};

export const completeTask = async (
  instanceId: number,
  taskId: number,
  data: CompleteTaskRequest,
): Promise<WfInstance> => {
  const response = await client.post(
    `/v1/workflow-instances/${instanceId}/tasks/${taskId}/complete`,
    data,
  );
  return response.data;
};

export const cancelWorkflow = async (
  instanceId: number,
  data: CancelWorkflowRequest,
): Promise<WfInstance> => {
  const response = await client.post(`/v1/workflow-instances/${instanceId}/cancel`, data);
  return response.data;
};

export const getMyTasks = async (departmentId: number): Promise<MyTask[]> => {
  const response = await client.get('/v1/workflow-instances/my-tasks', {
    params: { department_id: departmentId },
  });
  return response.data;
};
