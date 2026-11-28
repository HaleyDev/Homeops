import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getSkillsApi,
  publishSkillVersionApi,
  updateSkillApi,
  uploadSkillApi,
  validateSkillApi,
} from '#/api/skill-hub';

const requestClient = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  request: vi.fn(),
  upload: vi.fn(),
}));

vi.mock('#/api/request', () => ({ requestClient }));

beforeEach(() => {
  vi.clearAllMocks();
  requestClient.get.mockResolvedValue({ items: [] });
  requestClient.post.mockResolvedValue({});
  requestClient.request.mockResolvedValue({});
  requestClient.upload.mockResolvedValue({});
});

describe('api 请求', () => {
  it('把多标签序列化为后端要求的重复 tag 参数', async () => {
    const params = {
      keyword: 'demo',
      page: 2,
      page_size: 50,
      tags: ['Ops', '值班'],
    };
    await getSkillsApi(params);

    const call = requestClient.get.mock.calls[0];
    if (!call) throw new Error('未发起 Skill 列表请求');
    const [url, config] = call;
    expect(url).toBe('/skill-hub/skills/');
    expect(config.params).toEqual(params);
    expect(config.paramsSerializer.serialize(params)).toBe(
      `keyword=demo&page=2&page_size=50&tag=Ops&tag=${encodeURIComponent('值班')}`,
    );
  });

  it('dry-run 只提交文件，正式上传按标签语义决定是否携带 tags', async () => {
    const file = new File(['skill'], 'SKILL.md');
    await validateSkillApi(file);
    expect(requestClient.upload).toHaveBeenLastCalledWith(
      '/skill-hub/skills/validate/',
      { file },
      { timeout: 60_000 },
    );

    await uploadSkillApi(file, 'v1');
    expect(requestClient.upload).toHaveBeenLastCalledWith(
      '/skill-hub/skills/',
      { file, version: 'v1' },
      { timeout: 60_000 },
    );

    await uploadSkillApi(file, 'v2', []);
    expect(requestClient.upload).toHaveBeenLastCalledWith(
      '/skill-hub/skills/',
      { file, tags: '[]', version: 'v2' },
      { timeout: 60_000 },
    );
  });

  it('按名称更新标签并按名称和版本号发布历史版本', async () => {
    await updateSkillApi('demo-skill', ['Ops', '值班']);
    expect(requestClient.request).toHaveBeenCalledWith(
      '/skill-hub/skills/demo-skill/',
      { data: { tags: ['Ops', '值班'] }, method: 'PATCH' },
    );

    await publishSkillVersionApi('demo-skill', 'release 1');
    expect(requestClient.post).toHaveBeenCalledWith(
      '/skill-hub/skills/demo-skill/versions/release%201/publish/',
    );
  });
});
