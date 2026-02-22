/**
 * React Query hooks for workflow templates
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as workflowApi from '../../api/workflows';
import { WfTemplate, WfTemplateSave } from '../../types/workflow';

const QUERY_KEYS = {
  departments: ['workflow', 'departments'],
  templates: ['workflow', 'templates'],
  template: (id: number) => ['workflow', 'templates', id],
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
