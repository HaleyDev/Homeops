import type { UploadCustomRequestOptions } from 'naive-ui';
import type { VNode } from 'vue';

import type {
  Skill,
  SkillValidationReport,
  SkillVersion,
} from '#/api/skill-hub';

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SkillHubView from '../index.vue';
import SkillUploadPanel from '../components/skill-upload-panel.vue';
import SkillVersionDrawer from '../components/skill-version-drawer.vue';

const api = vi.hoisted(() => ({
  deleteSkillApi: vi.fn(),
  deleteSkillVersionApi: vi.fn(),
  getSkillsApi: vi.fn(),
  getSkillTagsApi: vi.fn(),
  getSkillVersionsApi: vi.fn(),
  publishSkillVersionApi: vi.fn(),
  updateSkillApi: vi.fn(),
  uploadSkillApi: vi.fn(),
  validateSkillApi: vi.fn(),
}));

const feedback = vi.hoisted(() => ({
  dialog: { warning: vi.fn() },
  message: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('#/api/skill-hub', () => api);
vi.mock('#/adapter/naive', () => feedback);

enableAutoUnmount(afterEach);

const stubs = {
  Alert: {
    name: 'NAlert',
    template: '<div><slot /></div>',
  },
  Button: {
    name: 'NButton',
    props: { disabled: Boolean, loading: Boolean },
    emits: ['click'],
    template:
      '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
  Card: {
    name: 'NCard',
    template:
      '<div><slot name="header" /><slot name="header-extra" /><slot /></div>',
  },
  DataTable: {
    name: 'NDataTable',
    props: {
      checkedRowKeys: Array,
      columns: Array,
      data: Array,
      pagination: Object,
    },
    template: '<div />',
  },
  Drawer: {
    name: 'NDrawer',
    props: { show: Boolean },
    template: '<div v-if="show"><slot /></div>',
  },
  DrawerContent: {
    name: 'NDrawerContent',
    template: '<div><slot /><slot name="footer" /></div>',
  },
  Input: {
    name: 'NInput',
    props: { type: String, value: String },
    emits: ['update:value'],
    template:
      '<textarea v-if="type === \'textarea\'" :value="value" /><input v-else :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  Modal: {
    name: 'NModal',
    props: { show: Boolean },
    template: '<div v-if="show"><slot /></div>',
  },
  Select: {
    name: 'NSelect',
    props: { value: Array },
    emits: ['update:value'],
    template: '<div />',
  },
  Spin: { name: 'NSpin', template: '<div><slot /></div>' },
  Tag: { name: 'NTag', template: '<span><slot /></span>' },
  Upload: {
    name: 'NUpload',
    props: { beforeUpload: Function, customRequest: Function },
    template: '<div><slot /></div>',
  },
  UploadDragger: {
    name: 'NUploadDragger',
    template: '<div><slot /></div>',
  },
};

function skill(overrides: Partial<Skill> = {}): Skill {
  return {
    can_manage: true,
    created_at: '2026-11-28T00:00:00Z',
    current_version: 'v1',
    description: '演示说明',
    download_path: '/api/skill-hub/skills/demo-skill/download/',
    file_count: 1,
    id: 1,
    name: 'demo-skill',
    owner: { id: 1, username: 'owner' },
    sha256: 'a'.repeat(64),
    size_bytes: 100,
    source_type: 'skill_md',
    status: 'ready',
    tags: ['Ops'],
    updated_at: '2026-11-28T00:00:00Z',
    version_count: 1,
    ...overrides,
  };
}

function version(overrides: Partial<SkillVersion> = {}): SkillVersion {
  return {
    created_at: '2026-11-28T00:00:00Z',
    description: '演示说明',
    download_path: '/api/skill-hub/skills/demo-skill/versions/v1/download/',
    file_count: 1,
    files: ['SKILL.md'],
    is_current: true,
    original_filename: 'SKILL.md',
    sha256: 'a'.repeat(64),
    size_bytes: 100,
    source_type: 'skill_md',
    status: 'ready',
    uploaded_by: { id: 1, username: 'owner' },
    version: 'v1',
    ...overrides,
  };
}

function report(
  overrides: Partial<SkillValidationReport> = {},
): SkillValidationReport {
  return {
    description: '解析说明',
    errors: [],
    file_count: 1,
    name: 'demo-skill',
    size_bytes: 100,
    source_type: 'skill_md',
    valid: true,
    warnings: [],
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

async function settle() {
  await flushPromises();
  await flushPromises();
}

function uploadOptions(file: File) {
  return {
    file: { file, name: file.name },
    onError: vi.fn(),
    onFinish: vi.fn(),
  } as unknown as UploadCustomRequestOptions;
}

function mountUploadPanel() {
  return mount(SkillUploadPanel, {
    global: { stubs },
    props: { tagOptions: [{ label: 'Ops', value: 'Ops' }] },
  });
}

function findButton(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper
    .findAll('button')
    .find((candidate) => candidate.text() === text);
  if (!button) throw new Error(`未找到按钮：${text}`);
  return button;
}

async function runValidation(
  wrapper: ReturnType<typeof mountUploadPanel>,
  file = new File(['skill'], 'SKILL.md'),
) {
  const customRequest = wrapper
    .findComponent({ name: 'NUpload' })
    .props('customRequest') as (
    options: UploadCustomRequestOptions,
  ) => Promise<void>;
  const options = uploadOptions(file);
  await customRequest(options);
  await settle();
  return options;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getSkillsApi.mockResolvedValue({
    items: [],
    page: 1,
    page_size: 20,
    total: 0,
  });
  api.getSkillTagsApi.mockResolvedValue({ items: [] });
  api.getSkillVersionsApi.mockResolvedValue({ items: [version()] });
  api.publishSkillVersionApi.mockResolvedValue(version());
  api.updateSkillApi.mockResolvedValue(skill());
  api.uploadSkillApi.mockResolvedValue(version());
  api.validateSkillApi.mockResolvedValue(report());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('上传面板', () => {
  it('展示只读解析结果，填写版本和标签后正式上传', async () => {
    const wrapper = mountUploadPanel();
    const file = new File(['skill'], 'SKILL.md');
    const options = await runValidation(wrapper, file);

    expect(options.onFinish).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain('demo-skill');
    expect(wrapper.text()).toContain('解析说明');
    expect(wrapper.find('input[placeholder*="name"]').exists()).toBe(false);

    await wrapper.find('input').setValue('v1');
    await wrapper
      .findComponent({ name: 'NSelect' })
      .vm.$emit('update:value', ['Ops']);
    await settle();
    const submit = findButton(wrapper, '确认上传');
    expect(submit.attributes('disabled')).toBeUndefined();
    await submit.trigger('click');
    await settle();

    expect(api.uploadSkillApi).toHaveBeenCalledWith(file, 'v1', ['Ops']);
    expect(wrapper.emitted('uploaded')).toEqual([['demo-skill']]);
  });

  it('校验失败或已有 Skill 非上传者时禁止提交', async () => {
    api.validateSkillApi.mockResolvedValueOnce(
      report({
        errors: [{ code: 'invalid_name', field: 'name', message: '名称错误' }],
        valid: false,
      }),
    );
    const invalidWrapper = mountUploadPanel();
    await runValidation(invalidWrapper);
    expect(invalidWrapper.text()).toContain('名称错误');
    expect(
      invalidWrapper
        .findAll('button')
        .find((button) => button.text() === '确认上传')
        ?.attributes('disabled'),
    ).toBeDefined();

    api.getSkillsApi.mockResolvedValueOnce({
      items: [skill({ can_manage: false })],
      page: 1,
      page_size: 100,
      total: 1,
    });
    const forbiddenWrapper = mountUploadPanel();
    await runValidation(forbiddenWrapper);
    await forbiddenWrapper.find('input').setValue('v2');
    expect(forbiddenWrapper.text()).toContain('不能上传新版本');
    expect(
      forbiddenWrapper
        .findAll('button')
        .find((button) => button.text() === '确认上传')
        ?.attributes('disabled'),
    ).toBeDefined();
    expect(api.uploadSkillApi).not.toHaveBeenCalled();
  });

  it('重新选择文件后忽略旧的慢校验响应', async () => {
    const first = deferred<SkillValidationReport>();
    api.validateSkillApi
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(
        report({ description: '新文件说明', name: 'new-skill' }),
      );
    const wrapper = mountUploadPanel();
    const customRequest = wrapper
      .findComponent({ name: 'NUpload' })
      .props('customRequest') as (
      options: UploadCustomRequestOptions,
    ) => Promise<void>;

    const oldRequest = customRequest(
      uploadOptions(new File(['old'], 'SKILL.md')),
    );
    await customRequest(uploadOptions(new File(['new'], 'new.zip')));
    await settle();
    expect(wrapper.text()).toContain('new-skill');
    first.resolve(report({ description: '旧文件说明', name: 'old-skill' }));
    await oldRequest;
    await settle();

    expect(wrapper.text()).toContain('new-skill');
    expect(wrapper.text()).not.toContain('old-skill');
  });
});

describe('skill hub 列表与提示语', () => {
  it('点击上传按钮打开悬浮窗，上传完成后自动关闭', async () => {
    const wrapper = mount(SkillHubView, { global: { stubs } });
    await settle();
    expect(wrapper.findComponent(SkillUploadPanel).exists()).toBe(false);

    await findButton(wrapper, '上传 Skill').trigger('click');
    await settle();
    const panel = wrapper.findComponent(SkillUploadPanel);
    expect(panel.exists()).toBe(true);

    panel.vm.$emit('uploaded', 'demo-skill');
    await settle();
    expect(wrapper.findComponent(SkillUploadPanel).exists()).toBe(false);
  });

  it('跨分页保留选择并复制包含所有 Skill 的提示语', async () => {
    const first = skill();
    const second = skill({
      current_version: 'v2',
      id: 2,
      name: 'second-skill',
    });
    api.getSkillsApi.mockImplementation(({ page: requestedPage = 1 }) =>
      Promise.resolve({
        items: requestedPage === 1 ? [first] : [second],
        page: requestedPage,
        page_size: 20,
        total: 2,
      }),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    const wrapper = mount(SkillHubView, { global: { stubs } });
    await settle();
    const table = wrapper.findComponent({ name: 'NDataTable' });
    table.vm.$emit('update:checked-row-keys', [1]);
    await settle();
    table.vm.$emit('update:page', 2);
    await settle();
    table.vm.$emit('update:checked-row-keys', [1, 2]);
    await settle();

    expect(table.props('checkedRowKeys')).toEqual([1, 2]);
    const promptButton = findButton(wrapper, '生成安装提示语');
    await promptButton.trigger('click');
    const promptInput = wrapper.find('textarea').element as HTMLTextAreaElement;
    expect(promptInput.value).toContain(
      '--skill demo-skill --skill second-skill',
    );
    const copyButton = findButton(wrapper, '一键复制');
    await copyButton.trigger('click');
    await settle();
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('--skill demo-skill --skill second-skill'),
    );
  });

  it('剪贴板接口被拒绝时使用兼容复制', async () => {
    api.getSkillsApi.mockResolvedValue({
      items: [skill()],
      page: 1,
      page_size: 20,
      total: 1,
    });
    const writeText = vi.fn().mockRejectedValue(new Error('Permission denied'));
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });

    const wrapper = mount(SkillHubView, { global: { stubs } });
    await settle();
    wrapper
      .findComponent({ name: 'NDataTable' })
      .vm.$emit('update:checked-row-keys', [1]);
    await settle();
    await findButton(wrapper, '生成安装提示语').trigger('click');
    await findButton(wrapper, '一键复制').trigger('click');
    await settle();

    expect(writeText).toHaveBeenCalledOnce();
    expect(execCommand).toHaveBeenCalledWith('copy');
    expect(feedback.message.success).toHaveBeenCalledWith('安装提示语已复制');
    expect(feedback.message.error).not.toHaveBeenCalled();
  });

  it('列表编辑弹窗按 Skill 名称提交标签', async () => {
    const current = skill();
    api.getSkillsApi.mockResolvedValue({
      items: [current],
      page: 1,
      page_size: 20,
      total: 1,
    });
    api.updateSkillApi.mockImplementation((_name, tags) =>
      Promise.resolve(skill({ tags })),
    );
    const wrapper = mount(SkillHubView, { global: { stubs } });
    await settle();
    const table = wrapper.findComponent({ name: 'NDataTable' });
    const actions = (
      table.props('columns') as Array<{
        key?: string;
        render?: (row: Skill) => VNode;
      }>
    ).find((column) => column.key === 'actions');
    if (!actions?.render) throw new Error('未找到列表操作列');
    const renderAction = actions.render;
    const actionWrapper = mount({ render: () => renderAction(current) });

    await findButton(actionWrapper, '编辑').trigger('click');
    await settle();
    expect(document.body.textContent).toContain(
      'name 和 description 由发布版本',
    );
    const save = [...document.body.querySelectorAll('button')].find(
      (button) => button.textContent?.trim() === '保存',
    );
    if (!save) throw new Error('未找到标签保存按钮');
    save.click();
    await settle();

    expect(api.updateSkillApi).toHaveBeenCalledWith('demo-skill', ['Ops']);
  });

  it('历史版本发布按 Skill 名称和版本号调用并刷新列表', async () => {
    const historical = version({
      description: '旧版说明',
      is_current: false,
      version: 'v1',
    });
    api.getSkillVersionsApi.mockResolvedValue({
      items: [version({ description: '新版说明', version: 'v2' }), historical],
    });
    const wrapper = mount(SkillVersionDrawer, {
      global: { stubs },
      props: { show: true, skill: skill({ current_version: 'v2' }) },
    });
    await settle();
    const table = wrapper.findComponent({ name: 'NDataTable' });
    const actions = (
      table.props('columns') as Array<{
        key?: string;
        render?: (row: SkillVersion) => VNode;
      }>
    ).find((column) => column.key === 'actions');
    if (!actions?.render) throw new Error('未找到版本操作列');
    const renderAction = actions.render;
    const actionWrapper = mount({ render: () => renderAction(historical) });
    await findButton(actionWrapper, '发布').trigger('click');

    const options = feedback.dialog.warning.mock.calls[0]?.[0] as {
      onPositiveClick: () => Promise<void>;
    };
    await options.onPositiveClick();
    await settle();

    expect(api.publishSkillVersionApi).toHaveBeenCalledWith('demo-skill', 'v1');
    expect(wrapper.emitted('changed')).toEqual([[false]]);
  });
});
