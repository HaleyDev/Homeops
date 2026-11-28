import { requestClient } from '#/api/request';

export interface SkillUser {
  id: number;
  username: string;
}

export type SkillSourceType = 'archive' | 'skill_md';

export interface Skill {
  can_manage: boolean;
  created_at: string;
  current_version: null | string;
  description: string;
  download_path: null | string;
  file_count: number;
  id: number;
  name: string;
  owner: null | SkillUser;
  sha256: string;
  size_bytes: number;
  source_type: null | SkillSourceType;
  status: 'deleting' | 'empty' | 'ready';
  tags: string[];
  updated_at: string;
  version_count: number;
}

export interface SkillVersion {
  created_at: string;
  description: string;
  download_path: string;
  file_count: number;
  files: string[];
  is_current: boolean;
  original_filename: string;
  sha256: string;
  size_bytes: number;
  source_type: SkillSourceType;
  status: 'deleting' | 'ready';
  uploaded_by: null | SkillUser;
  version: string;
}

export interface SkillIssue {
  code: string;
  field: string;
  message: string;
}

export interface SkillValidationReport {
  description: string;
  errors: SkillIssue[];
  file_count: number;
  name: string;
  size_bytes: number;
  source_type: null | SkillSourceType;
  valid: boolean;
  warnings: SkillIssue[];
}

export interface SkillListParams {
  keyword?: string;
  page?: number;
  page_size?: number;
  tags?: string[];
}

export interface SkillListResult {
  items: Skill[];
  page: number;
  page_size: number;
  total: number;
}

export interface SkillTag {
  count: number;
  name: string;
}

function serializeSkillListParams(params: SkillListParams) {
  const query = new URLSearchParams();
  if (params.keyword) query.set('keyword', params.keyword);
  if (params.page) query.set('page', String(params.page));
  if (params.page_size) query.set('page_size', String(params.page_size));
  for (const tag of params.tags ?? []) query.append('tag', tag);
  return query.toString();
}

export function getSkillsApi(params: SkillListParams = {}) {
  return requestClient.get<SkillListResult>('/skill-hub/skills/', {
    params,
    paramsSerializer: { serialize: serializeSkillListParams },
  });
}

export function validateSkillApi(file: File) {
  return requestClient.upload<SkillValidationReport>(
    '/skill-hub/skills/validate/',
    { file },
    { timeout: 60_000 },
  );
}

export function uploadSkillApi(file: File, version: string, tags?: string[]) {
  return requestClient.upload<SkillVersion>(
    '/skill-hub/skills/',
    {
      file,
      version,
      ...(tags === undefined ? {} : { tags: JSON.stringify(tags) }),
    },
    { timeout: 60_000 },
  );
}

export function getSkillTagsApi() {
  return requestClient.get<{ items: SkillTag[] }>('/skill-hub/skills/tags/');
}

export function getSkillVersionsApi(name: string) {
  return requestClient.get<{ items: SkillVersion[] }>(
    `/skill-hub/skills/${encodeURIComponent(name)}/versions/`,
  );
}

export function deleteSkillApi(name: string) {
  return requestClient.delete(`/skill-hub/skills/${encodeURIComponent(name)}/`);
}

export function updateSkillApi(name: string, tags: string[]) {
  return requestClient.request<Skill>(
    `/skill-hub/skills/${encodeURIComponent(name)}/`,
    { data: { tags }, method: 'PATCH' },
  );
}

export function publishSkillVersionApi(name: string, version: string) {
  return requestClient.post<SkillVersion>(
    `/skill-hub/skills/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}/publish/`,
  );
}

export function deleteSkillVersionApi(name: string, version: string) {
  return requestClient.delete(
    `/skill-hub/skills/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}/`,
  );
}
