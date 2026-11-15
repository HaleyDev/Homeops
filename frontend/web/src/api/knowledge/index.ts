import { requestClient } from '#/api/request';

export type KnowledgeDocumentStatus =
  | 'deleting'
  | 'failed'
  | 'processing'
  | 'ready'
  | 'uploaded';

export interface KnowledgeBase {
  created_at: string;
  description: string;
  document_count: number;
  id: number;
  name: string;
  updated_at: string;
}

export interface KnowledgeBaseListParams {
  keyword?: string;
  page?: number;
  page_size?: number;
}

export interface KnowledgeBaseListResult {
  items: KnowledgeBase[];
  page: number;
  page_size: number;
  total: number;
}

export interface CreateKnowledgeBaseParams {
  description: string;
  name: string;
}

export type UpdateKnowledgeBaseParams = Partial<CreateKnowledgeBaseParams>;

export interface KnowledgeDocument {
  created_at: string;
  error_message: string;
  extension: '.md' | '.txt';
  id: number;
  knowledge_base_id: number;
  mime_type: 'text/markdown' | 'text/plain';
  original_name: string;
  size_bytes: number;
  status: KnowledgeDocumentStatus;
}

export interface KnowledgeDocumentListResult {
  items: KnowledgeDocument[];
  page: number;
  page_size: number;
  total: number;
}

export function getKnowledgeBasesApi(params: KnowledgeBaseListParams = {}) {
  return requestClient.get<KnowledgeBaseListResult>('/knowledge-bases/', {
    params,
  });
}

export function getKnowledgeBaseApi(id: number) {
  return requestClient.get<KnowledgeBase>(`/knowledge-bases/${id}/`);
}

export function createKnowledgeBaseApi(data: CreateKnowledgeBaseParams) {
  return requestClient.post<KnowledgeBase>('/knowledge-bases/', data);
}

export function updateKnowledgeBaseApi(
  id: number,
  data: UpdateKnowledgeBaseParams,
) {
  return requestClient.request<KnowledgeBase>(`/knowledge-bases/${id}/`, {
    data,
    method: 'PATCH',
  });
}

export function deleteKnowledgeBaseApi(id: number) {
  return requestClient.delete(`/knowledge-bases/${id}/`);
}

export function getKnowledgeDocumentsApi(
  knowledgeBaseId: number,
  params: Pick<KnowledgeBaseListParams, 'page' | 'page_size'> = {},
) {
  return requestClient.get<KnowledgeDocumentListResult>(
    `/knowledge-bases/${knowledgeBaseId}/documents/`,
    { params },
  );
}

export function uploadKnowledgeDocumentApi(knowledgeBaseId: number, file: File) {
  return requestClient.upload<KnowledgeDocument>(
    `/knowledge-bases/${knowledgeBaseId}/documents/`,
    { file },
    { timeout: 60_000 },
  );
}

export function deleteKnowledgeDocumentApi(
  knowledgeBaseId: number,
  documentId: number,
) {
  return requestClient.delete(
    `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/`,
  );
}
