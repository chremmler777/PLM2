/**
 * Workflow API functions
 */
import client from './client';
import { Department, WfTemplate, WfTemplateList, WfTemplateSave } from '../types/workflow';

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
