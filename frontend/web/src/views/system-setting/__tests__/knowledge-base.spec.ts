import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { KnowledgeBase, KnowledgeDocument } from '#/api/knowledge';

import systemSettingRoutes from '#/router/routes/modules/system-setting';

import KnowledgeBaseView from '../knowledge-base.vue';
import KnowledgeDocumentPanel from '../components/knowledge-document-panel.vue';

const api = vi.hoisted(() => ({
  createKnowledgeBaseApi: vi.fn(),
  deleteKnowledgeBaseApi: vi.fn(),
  deleteKnowledgeDocumentApi: vi.fn(),
  getKnowledgeBaseApi: vi.fn(),
  getKnowledgeBasesApi: vi.fn(),
  getKnowledgeDocumentsApi: vi.fn(),
  updateKnowledgeBaseApi: vi.fn(),
  uploadKnowledgeDocumentApi: vi.fn(),
}));

const feedback = vi.hoisted(() => ({
  dialog: { warning: vi.fn() },
  message: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('#/api/knowledge', () => api);
vi.mock('#/adapter/naive', () => feedback);

const interactionStubs = {
  Alert: {
    name: 'NAlert',
    template: '<div><slot /></div>',
  },
  Card: {
    name: 'NCard',
    template:
      '<div><slot name="header" /><slot name="header-extra" /><slot /></div>',
  },
  Spin: {
    name: 'NSpin',
    template: '<div><slot /></div>',
  },
  Button: {
    name: 'NButton',
    props: { disabled: Boolean, loading: Boolean },
    emits: ['click'],
    template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
  DataTable: {
    name: 'NDataTable',
    props: { columns: Array, data: Array },
    template: '<div />',
  },
  Empty: {
    name: 'NEmpty',
    template: '<div />',
  },
  Input: {
    name: 'NInput',
    props: { modelValue: String },
    emits: ['update:value'],
    template: '<input />',
  },
  Pagination: {
    name: 'NPagination',
    template: '<div />',
  },
  Tag: {
    name: 'NTag',
    template: '<span><slot /></span>',
  },
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

function knowledgeBase(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return {
    created_at: '2026-11-15T04:00:00Z',
    description: '内部运维规范',
    document_count: 0,
    id: 1,
    name: '运维制度',
    updated_at: '2026-11-15T04:00:00Z',
    ...overrides,
  };
}

function knowledgeDocument(
  overrides: Partial<KnowledgeDocument> = {},
): KnowledgeDocument {
  return {
    created_at: '2026-11-15T04:05:00Z',
    error_message: '',
    extension: '.md',
    id: 10,
    knowledge_base_id: 1,
    mime_type: 'text/markdown',
    original_name: '值班规范.md',
    size_bytes: 1024,
    status: 'uploaded',
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getKnowledgeBasesApi.mockResolvedValue({
    items: [knowledgeBase()],
    page: 1,
    page_size: 20,
    total: 1,
  });
  api.getKnowledgeBaseApi.mockResolvedValue(knowledgeBase({ document_count: 1 }));
  api.getKnowledgeDocumentsApi.mockResolvedValue({
    items: [knowledgeDocument()],
    page: 1,
    page_size: 20,
    total: 1,
  });
  api.createKnowledgeBaseApi.mockImplementation((value) =>
    Promise.resolve(knowledgeBase({ id: 2, ...value })),
  );
  api.updateKnowledgeBaseApi.mockImplementation((id, value) =>
    Promise.resolve(knowledgeBase({ id, ...value })),
  );
  api.uploadKnowledgeDocumentApi.mockResolvedValue(knowledgeDocument());
});

afterEach(() => {
  vi.useRealTimers();
});

describe('系统设置菜单', () => {
  const parent = systemSettingRoutes[0]!;

  it('父目录包含两个独立子页面并默认进入模型供应商配置', () => {
    expect(parent).toMatchObject({
      name: 'SystemSetting',
      path: '/system-setting',
      redirect: '/system-setting/model-providers',
    });
    expect(parent.component).toBeUndefined();
    expect(
      parent.children?.map((child) => ({
        name: child.name,
        path: child.path,
        title: child.meta?.title,
      })),
    ).toEqual([
      {
        name: 'SystemSettingModelProviders',
        path: 'model-providers',
        title: 'page.modelProviderConfig',
      },
      {
        name: 'SystemSettingKnowledgeBase',
        path: 'knowledge-base',
        title: 'page.knowledgeBaseSetting',
      },
    ]);
  });

  it('父目录和两个子页面均保留超级管理员权限', () => {
    expect(parent.meta?.authority).toEqual(['super']);
    expect(parent.children).toHaveLength(2);
    for (const child of parent.children ?? []) {
      expect(child.meta?.authority).toEqual(['super']);
      expect(child.component).toBeTypeOf('function');
    }
  });
});

describe('知识库管理', () => {
  it('加载列表并执行搜索、新建和编辑', async () => {
    const wrapper = mount(KnowledgeBaseView, {
      global: {
        stubs: {
          KnowledgeBaseFormModal: true,
          KnowledgeDocumentPanel: true,
          ...interactionStubs,
        },
      },
    });
    await flushPromises();
    expect(api.getKnowledgeBasesApi).toHaveBeenCalledWith({
      keyword: undefined,
      page: 1,
      page_size: 20,
    });

    vi.useFakeTimers();
    wrapper.findComponent({ name: 'NInput' }).vm.$emit('update:value', '值班');
    await wrapper.vm.$nextTick();
    vi.advanceTimersByTime(350);
    await flushPromises();
    expect(api.getKnowledgeBasesApi).toHaveBeenCalledWith({
      keyword: '值班',
      page: 1,
      page_size: 20,
    });
    vi.useRealTimers();

    wrapper.findComponent({ name: 'KnowledgeBaseFormModal' }).vm.$emit('submit', {
      description: '新说明',
      name: '新知识库',
    });
    await flushPromises();
    expect(api.createKnowledgeBaseApi).toHaveBeenCalledWith({
      description: '新说明',
      name: '新知识库',
    });

    const editButton = wrapper
      .findAllComponents({ name: 'NButton' })
      .find((button) => button.text() === '编辑');
    await editButton?.trigger('click');
    wrapper.findComponent({ name: 'KnowledgeBaseFormModal' }).vm.$emit('submit', {
      description: '更新说明',
      name: '更新名称',
    });
    await flushPromises();
    expect(api.updateKnowledgeBaseApi).toHaveBeenCalledWith(1, {
      description: '更新说明',
      name: '更新名称',
    });
  });

  it('仅允许删除空知识库并在确认后刷新', async () => {
    const wrapper = mount(KnowledgeBaseView, {
      global: {
        stubs: {
          KnowledgeBaseFormModal: true,
          KnowledgeDocumentPanel: true,
          ...interactionStubs,
        },
      },
    });
    await flushPromises();
    const deleteButton = wrapper
      .findAllComponents({ name: 'NButton' })
      .find((button) => button.text() === '删除');
    expect(deleteButton?.props('disabled')).toBe(false);
    await deleteButton?.trigger('click');
    const options = feedback.dialog.warning.mock.calls[0]?.[0] as {
      onPositiveClick: () => Promise<void>;
    };
    await options.onPositiveClick();
    await flushPromises();
    expect(api.deleteKnowledgeBaseApi).toHaveBeenCalledWith(1);
  });

  it('非空知识库删除按钮禁用', async () => {
    api.getKnowledgeBasesApi.mockResolvedValue({
      items: [knowledgeBase({ document_count: 2 })],
      page: 1,
      page_size: 20,
      total: 1,
    });
    const wrapper = mount(KnowledgeBaseView, {
      global: {
        stubs: {
          KnowledgeBaseFormModal: true,
          KnowledgeDocumentPanel: true,
          ...interactionStubs,
        },
      },
    });
    await flushPromises();
    const deleteButton = wrapper
      .findAllComponents({ name: 'NButton' })
      .find((button) => button.text() === '删除');
    expect(deleteButton?.props('disabled')).toBe(true);
  });
});

describe('知识库文件面板', () => {
  it('上传前拒绝错误扩展名、空文件和超限文件', async () => {
    const wrapper = mount(KnowledgeDocumentPanel, {
      global: { stubs: interactionStubs },
      props: { knowledgeBase: knowledgeBase() },
    });
    await flushPromises();
    const upload = wrapper.findComponent({ name: 'NUpload' });
    const beforeUpload = upload.props('beforeUpload') as (options: {
      file: Record<string, unknown>;
    }) => boolean;

    for (const file of [
      { file: new File(['a'], 'a.pdf'), name: 'a.pdf' },
      { file: new File([], 'empty.md'), name: 'empty.md' },
      { file: { size: 20 * 1024 * 1024 + 1 }, name: 'large.md' },
    ]) {
      expect(beforeUpload({ file })).toBe(false);
    }
    expect(api.uploadKnowledgeDocumentApi).not.toHaveBeenCalled();
  });

  it('自定义上传传递单个 File 并刷新文件与文档数', async () => {
    const wrapper = mount(KnowledgeDocumentPanel, {
      global: { stubs: interactionStubs },
      props: { knowledgeBase: knowledgeBase() },
    });
    await flushPromises();
    const upload = wrapper.findComponent({ name: 'NUpload' });
    const customRequest = upload.props('customRequest') as (
      options: Record<string, unknown>,
    ) => Promise<void>;
    const file = new File(['# 新内容'], 'new.md', { type: 'text/markdown' });
    const onFinish = vi.fn();
    const onError = vi.fn();

    await customRequest({
      file: { file, name: file.name },
      onError,
      onFinish,
    });
    expect(api.uploadKnowledgeDocumentApi).toHaveBeenCalledWith(1, file);
    expect(onFinish).toHaveBeenCalledOnce();
    expect(onError).not.toHaveBeenCalled();
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(2);
    expect(wrapper.emitted('changed')).toHaveLength(1);
    expect(wrapper.emitted('uploading-change')).toEqual([[true], [false]]);
  });

  it('上传失败保留错误状态且不插入虚假记录', async () => {
    api.uploadKnowledgeDocumentApi.mockRejectedValue(new Error('409 conflict'));
    const wrapper = mount(KnowledgeDocumentPanel, {
      global: { stubs: interactionStubs },
      props: { knowledgeBase: knowledgeBase() },
    });
    await flushPromises();
    const upload = wrapper.findComponent({ name: 'NUpload' });
    const customRequest = upload.props('customRequest') as (
      options: Record<string, unknown>,
    ) => Promise<void>;
    const file = new File(['content'], 'duplicate.md');
    const onError = vi.fn();

    await customRequest({
      file: { file, name: file.name },
      onError,
      onFinish: vi.fn(),
    });
    expect(onError).toHaveBeenCalledOnce();
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted('changed')).toBeUndefined();
  });

  it('删除文件后刷新列表并通知父组件', async () => {
    const wrapper = mount(KnowledgeDocumentPanel, {
      global: { stubs: interactionStubs },
      props: { knowledgeBase: knowledgeBase({ document_count: 1 }) },
    });
    await flushPromises();
    const table = wrapper.findComponent({ name: 'NDataTable' });
    const columns = table.props('columns') as Array<{
      key: string;
      render?: (row: KnowledgeDocument) => {
        props: { onClick: () => void };
      };
    }>;
    columns.find((column) => column.key === 'actions')?.render?.(
      knowledgeDocument(),
    ).props.onClick();
    const options = feedback.dialog.warning.mock.calls[0]?.[0] as {
      onPositiveClick: () => Promise<void>;
    };
    await options.onPositiveClick();
    await flushPromises();
    expect(api.deleteKnowledgeDocumentApi).toHaveBeenCalledWith(1, 10);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(2);
    expect(wrapper.emitted('changed')).toHaveLength(1);
  });
});
