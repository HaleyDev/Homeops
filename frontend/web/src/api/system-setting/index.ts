import { requestClient } from '#/api/request';

export type LLMModelType = 'embedding' | 'text';

export interface LLMProvider {
  api_key_configured: boolean;
  base_url: string;
  created_at: string;
  extra_config: Record<string, unknown>;
  id: number;
  is_active: boolean;
  name: string;
  protocol: 'openai_compatible';
  slug: string;
  updated_at: string;
}

export interface LLMProviderPayload {
  api_key?: string;
  base_url: string;
  clear_api_key?: boolean;
  extra_config: Record<string, unknown>;
  is_active: boolean;
  name: string;
  protocol: 'openai_compatible';
  slug: string;
}

export interface LLMModel {
  created_at: string;
  display_name: string;
  id: number;
  is_active: boolean;
  model_key: string;
  model_type: LLMModelType;
  parameters: Record<string, unknown>;
  provider: number;
  provider_name: string;
  selected_for: LLMModelType | null;
  updated_at: string;
}

export interface LLMModelPayload {
  display_name: string;
  is_active: boolean;
  model_key: string;
  model_type: LLMModelType;
  parameters: Record<string, unknown>;
  provider: number;
}

export interface LLMSelection {
  category: LLMModelType;
  label: string;
  model: LLMModel | null;
}

export function getLLMProvidersApi() {
  return requestClient.get<LLMProvider[]>('/system-setting/llm/providers/');
}

export function createLLMProviderApi(data: LLMProviderPayload) {
  return requestClient.post<LLMProvider>(
    '/system-setting/llm/providers/',
    data,
  );
}

export function updateLLMProviderApi(
  id: number,
  data: Partial<LLMProviderPayload>,
) {
  return requestClient.request<LLMProvider>(
    `/system-setting/llm/providers/${id}/`,
    { data, method: 'PATCH' },
  );
}

export function deleteLLMProviderApi(id: number) {
  return requestClient.delete(`/system-setting/llm/providers/${id}/`);
}

export function getLLMModelsApi() {
  return requestClient.get<LLMModel[]>('/system-setting/llm/models/');
}

export function createLLMModelApi(data: LLMModelPayload) {
  return requestClient.post<LLMModel>('/system-setting/llm/models/', data);
}

export function updateLLMModelApi(id: number, data: Partial<LLMModelPayload>) {
  return requestClient.request<LLMModel>(`/system-setting/llm/models/${id}/`, {
    data,
    method: 'PATCH',
  });
}

export function deleteLLMModelApi(id: number) {
  return requestClient.delete(`/system-setting/llm/models/${id}/`);
}

export function getLLMSelectionsApi() {
  return requestClient.get<LLMSelection[]>('/system-setting/llm/selections/');
}

export function selectLLMModelApi(category: LLMModelType, modelId: number) {
  return requestClient.put<LLMModel>(
    `/system-setting/llm/selections/${category}/`,
    { model_id: modelId },
  );
}

export function clearLLMSelectionApi(category: LLMModelType) {
  return requestClient.delete(`/system-setting/llm/selections/${category}/`);
}
