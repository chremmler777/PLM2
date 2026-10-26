/**
 * Workflow API functions
 */
import client from './client';
import {
  Department, WfTemplate, WfTemplateList, WfTemplateSave,
  WfInstance, MyTask,
  StartWorkflowRequest, CompleteTaskRequest, CancelWorkflowRequest,
  DepartmentAdmin, DepartmentEscalation,
} from '../types/workflow';

/**
 * Every department, retired ones included (is_active false). The endpoint
 * lists active ones only by default; the full list is what name lookups on
 * old routings, meetings and tasks need. Pickers filter to is_active
 * themselves (see activeDepartments in lib/departments).
 */
export const getDepartments = async (): Promise<Department[]> => {
  const response = await client.get('/v1/workflow-templates/departments',
    { params: { include_retired: 1 } });
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
  // departmentId 0 means "my departments" — the backend scopes to the
  // current user's memberships when the param is omitted.
  const response = await client.get('/v1/workflow-instances/my-tasks', {
    params: departmentId > 0 ? { department_id: departmentId } : {},
  });
  return response.data;
};

// ============================================================================
// Departments admin page (migration 149: managers; memberships)
// ============================================================================

export const departmentsAdminApi = {
  list: async (): Promise<DepartmentAdmin[]> =>
    (await client.get('/v1/departments/admin')).data,
  setManager: async (departmentId: number, userId: number | null): Promise<DepartmentAdmin> =>
    (await client.put(`/v1/departments/${departmentId}/manager`, { user_id: userId })).data,
  setMembers: async (departmentId: number, userIds: number[]): Promise<DepartmentAdmin> =>
    (await client.put(`/v1/departments/${departmentId}/members`, { user_ids: userIds })).data,
  activate: async (departmentId: number): Promise<DepartmentAdmin> =>
    (await client.post(`/v1/departments/${departmentId}/activate`)).data,
  /** Every account (admin only), for the pickers. */
  users: async (): Promise<{ id: number; username: string; email: string; full_name: string | null; is_active: boolean }[]> =>
    (await client.get('/v1/users')).data,
};

/** My Tasks' "Late in my departments": empty departments = not a manager. */
export const getMyDepartmentEscalations = async (): Promise<{
  departments: { id: number; name: string }[]; items: DepartmentEscalation[];
}> => (await client.get('/v1/changes/my-department-escalations')).data;
