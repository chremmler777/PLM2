/**
 * React Query hooks for workflow templates and instances
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as workflowApi from '../../api/workflows';
import { WfTemplateSave, CompleteTaskRequest, CancelWorkflowRequest } from '../../types/workflow';

const QUERY_KEYS = {
  departments: ['workflow', 'departments'],
  templates: ['workflow', 'templates'],
  template: (id: number) => ['workflow', 'templates', id],
  revisionWorkflow: (revisionId: number) => ['workflow', 'revision', revisionId, 'instance'],
  myTasks: (deptId: number) => ['workflow', 'my-tasks', deptId],
};

export const useDepartments = () => {
  return useQuery({
    queryKey: QUERY_KEYS.departments,
    queryFn: workflowApi.getDepartments,
  });
};

export const useTemplates = () => {
  return useQuery({
    queryKey: QUERY_KEYS.templates,
    queryFn: workflowApi.listTemplates,
  });
};

export const useTemplate = (templateId: number) => {
  return useQuery({
    queryKey: QUERY_KEYS.template(templateId),
    queryFn: () => workflowApi.getTemplate(templateId),
  });
};

export const useCreateTemplate = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: WfTemplateSave) => workflowApi.createTemplate(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.templates });
    },
  });
};

export const useUpdateTemplate = (templateId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: WfTemplateSave) => workflowApi.updateTemplate(templateId, data),
    onSuccess: (updated) => {
      queryClient.setQueryData(QUERY_KEYS.template(templateId), updated);
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.templates });
    },
  });
};

export const useDeactivateTemplate = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (templateId: number) => workflowApi.deactivateTemplate(templateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.templates });
    },
  });
};

// ============================================================================
// Phase 3c: Workflow instance hooks
// ============================================================================

export const useRevisionWorkflow = (revisionId: number) => {
  return useQuery({
    queryKey: QUERY_KEYS.revisionWorkflow(revisionId),
    queryFn: () => workflowApi.getRevisionWorkflow(revisionId),
    enabled: revisionId > 0,
  });
};

export const useStartWorkflow = (revisionId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { template_id: number }) => workflowApi.startWorkflow(revisionId, data),
    onSuccess: (instance) => {
      queryClient.setQueryData(QUERY_KEYS.revisionWorkflow(revisionId), instance);
    },
  });
};

export const useCompleteTask = (instanceId: number, revisionId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskId, data }: { taskId: number; data: CompleteTaskRequest }) =>
      workflowApi.completeTask(instanceId, taskId, data),
    onSuccess: (instance) => {
      queryClient.setQueryData(QUERY_KEYS.revisionWorkflow(revisionId), instance);
      // Invalidate my-tasks queries for all departments
      queryClient.invalidateQueries({ queryKey: ['workflow', 'my-tasks'] });
    },
  });
};

export const useCancelWorkflow = (instanceId: number, revisionId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CancelWorkflowRequest) => workflowApi.cancelWorkflow(instanceId, data),
    onSuccess: (instance) => {
      queryClient.setQueryData(QUERY_KEYS.revisionWorkflow(revisionId), instance);
    },
  });
};

export const useMyTasks = (departmentId: number) => {
  return useQuery({
    queryKey: QUERY_KEYS.myTasks(departmentId),
    queryFn: () => workflowApi.getMyTasks(departmentId),
    enabled: departmentId > 0,
  });
};
