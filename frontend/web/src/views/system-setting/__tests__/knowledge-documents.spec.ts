import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { VNode } from 'vue';

import type { KnowledgeBase, KnowledgeDocument } from '#/api/knowledge';

import KnowledgeDocumentPanel from '../components/knowledge-document-panel.vue';

const api = vi.hoisted(() => ({
  deleteKnowledgeDocumentApi: vi.fn(),
  getKnowledgeDocumentsApi: vi.fn(),
  retryKnowledgeDocumentApi: vi.fn(),
  uploadKnowledgeDocumentApi: vi.fn(),
}));

const feedback = vi.hoisted(() => ({
  dialog: { warning: vi.fn() },
  message: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('#/api/knowledge', () => api);
vi.mock('#/adapter/naive', () => feedback);

enableAutoUnmount(afterEach);

const interactionStubs = {
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
    props: { columns: Array, data: Array, pagination: Object },
    template: '<div />',
  },
  Empty: { name: 'NEmpty', template: '<div />' },
  Tag: { name: 'NTag', template: '<span><slot /></span>' },
  Upload: {
    name: 'NUpload',
    props: { customRequest: Function },
    template: '<div><slot /></div>',
  },
  UploadDragger: { name: 'NUploadDragger', template: '<div><slot /></div>' },
};

function knowledgeBase(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return {
    created_at: '2026-11-15T04:00:00Z',
    description: '内部运维规范',
    document_count: 1,
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
    processed_at: null,
    size_bytes: 1024,
    status: 'ready',
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, reject, resolve };
}

async function settle() {
  await flushPromises();
  await flushPromises();
}

async function advance(milliseconds: number) {
  await vi.advanceTimersByTimeAsync(milliseconds);
  await settle();
}

function mountPanel(
  documents: KnowledgeDocument[],
  props: { active?: boolean; knowledgeBase?: KnowledgeBase | null } = {},
) {
  api.getKnowledgeDocumentsApi.mockResolvedValue({ items: documents });
  return mount(KnowledgeDocumentPanel, {
    global: { stubs: interactionStubs },
    props: {
      active: true,
      knowledgeBase: knowledgeBase(),
      ...props,
    },
  });
}

function tableData(wrapper: ReturnType<typeof mountPanel>) {
  return wrapper
    .findComponent({ name: 'NDataTable' })
    .props('data') as KnowledgeDocument[];
}

function column(wrapper: ReturnType<typeof mountPanel>, key: string) {
  const columns = wrapper
    .findComponent({ name: 'NDataTable' })
    .props('columns') as Array<{
    key: string;
    render?: (row: KnowledgeDocument) => VNode;
  }>;
  return columns.find((item) => item.key === key)!;
}

function actionButtons(
  wrapper: ReturnType<typeof mountPanel>,
  document: KnowledgeDocument,
) {
  const actions = column(wrapper, 'actions').render!(document);
  return (actions.children as unknown[]).filter(Boolean) as VNode[];
}

function latestDialog() {
  return feedback.dialog.warning.mock.calls.at(-1)?.[0] as {
    onPositiveClick: () => Promise<void>;
  };
}

function setVisibility(value: 'hidden' | 'visible') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value,
  });
  document.dispatchEvent(new Event('visibilitychange'));
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getKnowledgeDocumentsApi.mockResolvedValue({ items: [] });
  api.retryKnowledgeDocumentApi.mockResolvedValue(
    knowledgeDocument({ status: 'uploaded' }),
  );
  api.uploadKnowledgeDocumentApi.mockResolvedValue(
    knowledgeDocument({ status: 'uploaded' }),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value: 'visible',
  });
});

describe('知识库文件轮询', () => {
  it('多个待处理文件共用一个 interval，每五秒请求完整列表并在终态后停止', async () => {
    vi.useFakeTimers();
    const setIntervalSpy = vi.spyOn(window, 'setInterval');
    const pending = [
      knowledgeDocument({ status: 'uploaded' }),
      knowledgeDocument({ id: 11, status: 'processing' }),
    ];
    const wrapper = mountPanel(pending);
    await settle();

    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(1);
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    await advance(5000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(2);
    await advance(10_000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(4);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenLastCalledWith(1);

    api.getKnowledgeDocumentsApi.mockResolvedValue({
      items: [
        knowledgeDocument(),
        knowledgeDocument({ id: 11, status: 'failed' }),
      ],
    });
    await advance(5000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(5);
    expect(vi.getTimerCount()).toBe(0);
    await advance(10_000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(5);
    wrapper.unmount();
  });

  it('页签隐藏、浏览器隐藏和组件卸载都会停止轮询', async () => {
    vi.useFakeTimers();
    const wrapper = mountPanel([knowledgeDocument({ status: 'processing' })]);
    await settle();
    expect(vi.getTimerCount()).toBe(1);

    await wrapper.setProps({ active: false });
    await settle();
    expect(vi.getTimerCount()).toBe(0);
    await advance(5000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ active: true });
    await settle();
    expect(vi.getTimerCount()).toBe(1);
    setVisibility('hidden');
    await settle();
    expect(vi.getTimerCount()).toBe(0);
    await advance(5000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(1);

    setVisibility('visible');
    await settle();
    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('慢轮询期间跳过重叠请求，完成后才允许下一次轮询', async () => {
    vi.useFakeTimers();
    const wrapper = mountPanel([knowledgeDocument({ status: 'uploaded' })]);
    await settle();
    const slow = deferred<{ items: KnowledgeDocument[] }>();
    api.getKnowledgeDocumentsApi
      .mockImplementationOnce(() => slow.promise)
      .mockResolvedValue({ items: [knowledgeDocument()] });

    await advance(5000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(2);
    await advance(5000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(2);

    slow.resolve({ items: [knowledgeDocument({ status: 'processing' })] });
    await settle();
    await advance(5000);
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
    wrapper.unmount();
  });

  it('切换知识库清理旧 timer，旧响应不能覆盖新列表', async () => {
    vi.useFakeTimers();
    const first = deferred<{ items: KnowledgeDocument[] }>();
    const second = deferred<{ items: KnowledgeDocument[] }>();
    api.getKnowledgeDocumentsApi.mockImplementation((id: number) =>
      id === 1 ? first.promise : second.promise,
    );
    const wrapper = mount(KnowledgeDocumentPanel, {
      global: { stubs: interactionStubs },
      props: { active: true, knowledgeBase: knowledgeBase() },
    });
    await settle();
    await wrapper.setProps({
      knowledgeBase: knowledgeBase({ id: 2, name: '新知识库' }),
    });
    await settle();

    second.resolve({
      items: [knowledgeDocument({ id: 20, knowledge_base_id: 2 })],
    });
    await settle();
    expect(tableData(wrapper).map((item) => item.id)).toEqual([20]);
    first.resolve({
      items: [knowledgeDocument({ id: 10, status: 'uploaded' })],
    });
    await settle();
    expect(tableData(wrapper).map((item) => item.id)).toEqual([20]);
    expect(vi.getTimerCount()).toBe(0);

    api.getKnowledgeDocumentsApi.mockResolvedValue({ items: [] });
    await advance(10_000);
    expect(
      api.getKnowledgeDocumentsApi.mock.calls.filter(([id]) => id === 1),
    ).toHaveLength(1);
    wrapper.unmount();
  });

  it('静默失败只提示一次，成功刷新后恢复提示状态', async () => {
    vi.useFakeTimers();
    const wrapper = mountPanel([knowledgeDocument({ status: 'processing' })]);
    await settle();
    api.getKnowledgeDocumentsApi.mockRejectedValue(new Error('network'));

    await advance(5000);
    await advance(15_000);
    expect(feedback.message.error).toHaveBeenCalledTimes(1);
    expect(feedback.message.error).toHaveBeenCalledWith(
      '文件状态刷新失败，将在下次轮询重试',
    );

    api.getKnowledgeDocumentsApi.mockResolvedValue({
      items: [knowledgeDocument({ status: 'processing' })],
    });
    await advance(5000);
    api.getKnowledgeDocumentsApi.mockRejectedValue(new Error('network'));
    await advance(5000);
    expect(feedback.message.error).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it('静默刷新保留本地分页，并且列表请求不携带分页参数', async () => {
    vi.useFakeTimers();
    const documents = Array.from({ length: 21 }, (_, index) =>
      knowledgeDocument({ id: index + 1, status: 'processing' }),
    );
    const wrapper = mountPanel(documents);
    await settle();
    const table = wrapper.findComponent({ name: 'NDataTable' });
    table.vm.$emit('update:page', 2);
    await settle();

    await advance(5000);
    expect(table.props('pagination')).toMatchObject({ page: 2, pageSize: 20 });
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledWith(1);
    expect(api.getKnowledgeDocumentsApi).not.toHaveBeenCalledWith(
      1,
      expect.anything(),
    );
    wrapper.unmount();
  });

  it('新上传进入待处理状态后重新启动轮询', async () => {
    vi.useFakeTimers();
    const wrapper = mountPanel([knowledgeDocument()]);
    await settle();
    expect(vi.getTimerCount()).toBe(0);
    api.getKnowledgeDocumentsApi.mockResolvedValue({
      items: [knowledgeDocument({ status: 'uploaded' })],
    });
    const customRequest = wrapper
      .findComponent({ name: 'NUpload' })
      .props('customRequest') as (
      options: Record<string, unknown>,
    ) => Promise<void>;
    const file = new File(['content'], 'new.md');

    await customRequest({
      file: { file, name: file.name },
      onError: vi.fn(),
      onFinish: vi.fn(),
    });
    await settle();
    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
  });
});

describe('知识库文件错误与重试', () => {
  it('只有 failed 显示纯文本错误和重试，长错误不会作为 HTML 执行', async () => {
    const error = '<img src=x onerror=alert(1)>'.repeat(20);
    const wrapper = mountPanel([
      knowledgeDocument({ status: 'failed', error_message: error }),
    ]);
    await settle();

    const failed = knowledgeDocument({
      status: 'failed',
      error_message: error,
    });
    expect(actionButtons(wrapper, failed)).toHaveLength(2);
    const status = column(wrapper, 'status').render!(failed);
    const tooltip = (status.children as unknown[])[1] as VNode;
    const content = (tooltip.children as { default: () => VNode }).default();
    expect(content.children).toBe(error);
    expect(content.props).not.toHaveProperty('innerHTML');

    for (const statusValue of ['uploaded', 'processing', 'ready'] as const) {
      expect(
        actionButtons(wrapper, knowledgeDocument({ status: statusValue })),
      ).toHaveLength(1);
    }
  });

  it('retry 仅禁用当前文件，重复确认不并发，成功后清空错误并刷新', async () => {
    vi.useFakeTimers();
    const failed = knowledgeDocument({
      status: 'failed',
      error_message: '失败',
    });
    const other = knowledgeDocument({
      id: 11,
      status: 'failed',
      error_message: '其他失败',
    });
    const wrapper = mountPanel([failed, other]);
    await settle();
    const pending = deferred<KnowledgeDocument>();
    api.retryKnowledgeDocumentApi.mockReturnValue(pending.promise);
    const retried = knowledgeDocument({ status: 'uploaded' });
    api.getKnowledgeDocumentsApi.mockResolvedValue({ items: [retried, other] });

    actionButtons(wrapper, failed)[0]!.props!.onClick();
    const first = latestDialog().onPositiveClick();
    const duplicate = latestDialog().onPositiveClick();
    await duplicate;
    expect(api.retryKnowledgeDocumentApi).toHaveBeenCalledTimes(1);
    expect(api.retryKnowledgeDocumentApi).toHaveBeenCalledWith(1, 10);
    expect(actionButtons(wrapper, failed)[0]!.props!.disabled).toBe(true);
    expect(actionButtons(wrapper, other)[0]!.props!.disabled).toBe(false);

    pending.resolve(retried);
    await first;
    await settle();
    expect(tableData(wrapper)[0]).toMatchObject({
      error_message: '',
      status: 'uploaded',
    });
    expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(2);
    expect(feedback.message.success).toHaveBeenCalledWith(
      '已重新投递向量化任务',
    );
    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
  });

  it.each([
    { expectedStatus: 'ready', status: 409 },
    { expectedStatus: 'failed', status: 503 },
  ] as const)(
    'retry 返回 $status 后刷新全量列表并保留正确状态',
    async ({ expectedStatus, status }) => {
      const failed = knowledgeDocument({
        status: 'failed',
        error_message: '失败',
      });
      const wrapper = mountPanel([failed]);
      await settle();
      api.retryKnowledgeDocumentApi.mockRejectedValue({ response: { status } });
      api.getKnowledgeDocumentsApi.mockResolvedValue({
        items: [
          knowledgeDocument({
            status: expectedStatus,
            error_message: status === 503 ? '失败' : '',
          }),
        ],
      });

      actionButtons(wrapper, failed)[0]!.props!.onClick();
      await latestDialog().onPositiveClick();
      await settle();

      expect(api.getKnowledgeDocumentsApi).toHaveBeenCalledTimes(2);
      expect(tableData(wrapper)[0]?.status).toBe(expectedStatus);
      expect(actionButtons(wrapper, tableData(wrapper)[0]!)).toHaveLength(
        status === 503 ? 2 : 1,
      );
      if (status === 409) {
        expect(feedback.message.error).toHaveBeenCalledWith(
          '文件状态已变化，已刷新列表',
        );
      } else {
        expect(feedback.message.error).toHaveBeenCalledWith(
          '向量化任务投递失败，请稍后重试',
        );
        expect(tableData(wrapper)[0]?.error_message).toBe('失败');
      }
    },
  );
});
