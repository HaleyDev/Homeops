<template>
  <NCard>
    <template #header>
      <span class="break-words">
        {{ knowledgeBase ? knowledgeBase.name : '文件管理' }}
      </span>
    </template>
    <template #header-extra>
      <NTag v-if="knowledgeBase" size="small" type="info">
        {{ knowledgeBase.document_count }} 个文件
      </NTag>
    </template>

    <NEmpty v-if="!knowledgeBase" description="请先选择或新建一个知识库" />
    <template v-else>
      <p
        class="text-muted-foreground mb-4 whitespace-pre-wrap break-words text-sm"
      >
        {{ knowledgeBase.description }}
      </p>

      <NUpload
        v-model:file-list="fileList"
        :max="1"
        accept=".md,.txt,text/markdown,text/plain"
        :disabled="uploading"
        :custom-request="customUpload"
        :before-upload="beforeUpload"
      >
        <NUploadDragger>
          <div class="py-4">
            <div class="mb-2 font-medium">
              {{ uploading ? '文件上传中，请稍候' : '点击或拖拽上传单个文件' }}
            </div>
            <div class="text-muted-foreground text-xs">
              仅支持 Markdown / TXT，文件必须为非空 UTF-8 文本，最大 20 MiB
            </div>
          </div>
        </NUploadDragger>
      </NUpload>

      <div class="mb-3 mt-6 flex items-center justify-between">
        <h3 class="font-medium">历史文件</h3>
        <NButton
          size="small"
          quaternary
          :loading="loading"
          @click="refreshAllDocuments()"
        >
          刷新
        </NButton>
      </div>
      <NDataTable
        :columns="columns"
        :data="documents"
        :loading="loading"
        :pagination="pagination"
        :row-key="(row: KnowledgeDocument) => row.id"
        :scroll-x="900"
        @update:page="changePage"
        @update:page-size="changePageSize"
      />
    </template>
  </NCard>
</template>

<script setup lang="ts">
import type {
  DataTableColumns,
  UploadCustomRequestOptions,
  UploadFileInfo,
  UploadSettledFileInfo,
} from 'naive-ui';

import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeDocumentStatus,
} from '#/api/knowledge';

import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { IconifyIcon } from '@vben/icons';
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NTag,
  NTooltip,
  NUpload,
  NUploadDragger,
} from 'naive-ui';

import { dialog, message } from '#/adapter/naive';
import {
  deleteKnowledgeDocumentApi,
  getKnowledgeDocumentsApi,
  retryKnowledgeDocumentApi,
  uploadKnowledgeDocumentApi,
} from '#/api/knowledge';

const MAX_FILE_SIZE = 20 * 1024 * 1024;
const POLL_INTERVAL = 5000;

const props = withDefaults(
  defineProps<{
    active?: boolean;
    knowledgeBase: KnowledgeBase | null;
  }>(),
  { active: true },
);

const emit = defineEmits<{
  changed: [];
  'uploading-change': [value: boolean];
}>();

const documents = ref<KnowledgeDocument[]>([]);
const fileList = ref<UploadFileInfo[]>([]);
const loading = ref(false);
const uploading = ref(false);
const deletingId = ref<null | number>(null);
const retryingId = ref<null | number>(null);
const page = ref(1);
const pageSize = ref(20);
const pageVisible = ref(true);
let pollTimer: null | number = null;
let pollInFlight = false;
let loadSequence = 0;
let silentFailureNotified = false;

const statusMeta: Record<
  KnowledgeDocumentStatus,
  { label: string; type: 'default' | 'error' | 'info' | 'success' | 'warning' }
> = {
  deleting: { label: '删除中', type: 'warning' },
  failed: { label: '向量化失败', type: 'error' },
  processing: { label: '向量化中', type: 'info' },
  ready: { label: '已向量化', type: 'success' },
  uploaded: { label: '等待向量化', type: 'default' },
};

const pagination = computed(() => ({
  itemCount: documents.value.length,
  page: page.value,
  pageSize: pageSize.value,
  pageSizes: [10, 20, 50],
  showSizePicker: true,
}));

const columns: DataTableColumns<KnowledgeDocument> = [
  {
    key: 'original_name',
    title: '文件名',
    ellipsis: { tooltip: true },
    minWidth: 180,
  },
  {
    key: 'size_bytes',
    title: '大小',
    width: 100,
    render: (row) => formatSize(row.size_bytes),
  },
  {
    key: 'created_at',
    title: '上传时间',
    width: 170,
    render: (row) => formatTime(row.created_at),
  },
  {
    key: 'processed_at',
    title: '处理完成时间',
    width: 170,
    render: (row) => formatTime(row.processed_at),
  },
  {
    key: 'status',
    title: '状态',
    minWidth: 170,
    render: (row) => {
      const meta = statusMeta[row.status];
      const label =
        row.status === 'deleting' && row.error_message
          ? '删除失败，可重试'
          : meta.label;
      return h('div', [
        h(NTag, { size: 'small', type: meta.type }, { default: () => label }),
        row.status === 'failed'
          ? h(
              NTooltip,
              { trigger: 'hover' },
              {
                trigger: () =>
                  h(
                    'button',
                    {
                      class: 'ml-2 cursor-pointer text-xs text-error underline',
                      type: 'button',
                    },
                    '查看原因',
                  ),
                default: () =>
                  h(
                    'div',
                    { class: 'max-w-md whitespace-pre-wrap break-words' },
                    row.error_message || '向量化失败，请重试或联系管理员',
                  ),
              },
            )
          : null,
        row.status === 'deleting' && row.error_message
          ? h(
              'div',
              { class: 'text-muted-foreground mt-1 text-xs' },
              row.error_message,
            )
          : null,
      ]);
    },
  },
  {
    key: 'actions',
    title: '操作',
    width: 150,
    render: (row) =>
      h('div', { class: 'flex items-center gap-2' }, [
        row.status === 'failed'
          ? h(
              NButton,
              {
                disabled: retryingId.value === row.id,
                loading: retryingId.value === row.id,
                size: 'small',
                text: true,
                type: 'primary',
                onClick: () => confirmRetry(row),
              },
              {
                default: () => [
                  h(IconifyIcon, { icon: 'lucide:rotate-cw' }),
                  '重试',
                ],
              },
            )
          : null,
        h(
          NButton,
          {
            disabled: uploading.value || deletingId.value !== null,
            loading: deletingId.value === row.id,
            size: 'small',
            text: true,
            type: 'error',
            onClick: () => confirmDelete(row),
          },
          {
            default: () =>
              row.status === 'deleting' && row.error_message
                ? '重试删除'
                : '删除',
          },
        ),
      ]),
  },
];

watch(
  () =>
    [
      props.knowledgeBase?.id ?? null,
      documents.value.some((item) =>
        ['uploaded', 'processing'].includes(item.status),
      ),
      props.active,
      pageVisible.value,
    ] as const,
  ([baseId, hasPending, active, visible], previous, onCleanup) => {
    if (baseId !== previous?.[0]) {
      loadSequence += 1;
      fileList.value = [];
      documents.value = [];
      page.value = 1;
      if (baseId) void refreshAllDocuments();
      return;
    }
    if (!baseId || !hasPending || !active || !visible) return;

    const timer = window.setInterval(() => {
      void refreshAllDocuments({ silent: true });
    }, POLL_INTERVAL);
    pollTimer = timer;
    onCleanup(() => {
      window.clearInterval(timer);
      if (pollTimer === timer) pollTimer = null;
    });
  },
  { immediate: true },
);

onMounted(() => {
  pageVisible.value = document.visibilityState !== 'hidden';
  document.addEventListener('visibilitychange', handleVisibilityChange);
});

onBeforeUnmount(() => {
  loadSequence += 1;
  stopPolling();
  document.removeEventListener('visibilitychange', handleVisibilityChange);
});

function handleVisibilityChange() {
  pageVisible.value = document.visibilityState !== 'hidden';
}

function stopPolling() {
  if (pollTimer !== null) window.clearInterval(pollTimer);
  pollTimer = null;
}

function formatSize(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
}

function formatTime(value: null | string) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function validateFile(file: UploadSettledFileInfo) {
  if (!file.file) return '无法读取所选文件';
  if (!/\.(md|txt)$/i.test(file.name)) return '仅支持 .md 或 .txt 文件';
  if (file.file.size === 0) return '不能上传空文件';
  if (file.file.size > MAX_FILE_SIZE) return '文件大小不能超过 20 MiB';
  return null;
}

function beforeUpload({ file }: { file: UploadSettledFileInfo }) {
  const error = validateFile(file);
  if (error) {
    message.error(error);
    return false;
  }
  return true;
}

async function customUpload(options: UploadCustomRequestOptions) {
  const knowledgeBaseId = props.knowledgeBase?.id;
  const error = validateFile(options.file);
  if (!knowledgeBaseId || !options.file.file || error) {
    if (error) message.error(error);
    options.onError();
    return;
  }

  loadSequence += 1;
  uploading.value = true;
  emit('uploading-change', true);
  try {
    const uploaded = await uploadKnowledgeDocumentApi(
      knowledgeBaseId,
      options.file.file,
    );
    options.onFinish();
    fileList.value = [];
    if (uploaded.status === 'failed') {
      message.error('文件已上传，但向量化任务投递失败，请重试');
    } else {
      message.success('文件已上传，等待向量化');
    }
    if (knowledgeBaseId !== props.knowledgeBase?.id) return;
    page.value = 1;
    await refreshAllDocuments();
    emit('changed');
  } catch {
    options.onError();
  } finally {
    uploading.value = false;
    emit('uploading-change', false);
  }
}

async function refreshAllDocuments({ silent = false } = {}) {
  const knowledgeBaseId = props.knowledgeBase?.id;
  if (!knowledgeBaseId) {
    documents.value = [];
    return true;
  }
  if (silent && pollInFlight) return false;

  const sequence = ++loadSequence;
  if (silent) pollInFlight = true;
  if (!silent) loading.value = true;
  try {
    const result = await getKnowledgeDocumentsApi(knowledgeBaseId);
    if (
      sequence !== loadSequence ||
      knowledgeBaseId !== props.knowledgeBase?.id
    )
      return false;
    documents.value = result.items;
    const lastPage = Math.max(
      1,
      Math.ceil(result.items.length / pageSize.value),
    );
    page.value = Math.min(page.value, lastPage);
    silentFailureNotified = false;
    return true;
  } catch {
    if (sequence !== loadSequence) return false;
    if (silent) {
      if (!silentFailureNotified) {
        message.error('文件状态刷新失败，将在下次轮询重试');
        silentFailureNotified = true;
      }
    } else {
      message.error('文件列表加载失败，请重试');
    }
    return false;
  } finally {
    if (silent) pollInFlight = false;
    if (sequence === loadSequence && !silent) loading.value = false;
  }
}

function changePage(value: number) {
  page.value = value;
}

function changePageSize(value: number) {
  pageSize.value = value;
  page.value = 1;
}

function confirmRetry(document: KnowledgeDocument) {
  if (document.status !== 'failed' || retryingId.value === document.id) return;
  dialog.warning({
    title: '重试向量化',
    content: `将对“${document.original_name}”重新分块并调用 Embedding 服务，确认继续吗？`,
    positiveText: '重试',
    negativeText: '取消',
    onPositiveClick: async () => {
      const knowledgeBaseId = props.knowledgeBase?.id;
      if (!knowledgeBaseId || retryingId.value === document.id) return;
      loadSequence += 1;
      retryingId.value = document.id;
      try {
        const retried = await retryKnowledgeDocumentApi(
          knowledgeBaseId,
          document.id,
        );
        if (knowledgeBaseId !== props.knowledgeBase?.id) return;
        documents.value = documents.value.map((item) =>
          item.id === retried.id ? retried : item,
        );
        message.success('已重新投递向量化任务');
        await refreshAllDocuments();
      } catch (error) {
        if (knowledgeBaseId !== props.knowledgeBase?.id) return;
        const status = getErrorStatus(error);
        if (status === 409) {
          message.error('文件状态已变化，已刷新列表');
        } else if (status === 503) {
          message.error('向量化任务投递失败，请稍后重试');
        } else {
          message.error('向量化重试失败，请稍后重试');
        }
        await refreshAllDocuments();
      } finally {
        retryingId.value = null;
      }
    },
  });
}

function getErrorStatus(error: unknown) {
  if (!error || typeof error !== 'object') return null;
  const response = (error as { response?: { status?: number } }).response;
  return response?.status ?? (error as { status?: number }).status ?? null;
}

function confirmDelete(document: KnowledgeDocument) {
  dialog.warning({
    title: document.status === 'deleting' ? '重试删除文件' : '删除文件',
    content: `确认删除“${document.original_name}”吗？原文、分块向量和数据库记录将同时清理。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      const knowledgeBaseId = props.knowledgeBase?.id;
      if (!knowledgeBaseId) return;
      loadSequence += 1;
      deletingId.value = document.id;
      try {
        await deleteKnowledgeDocumentApi(knowledgeBaseId, document.id);
        if (knowledgeBaseId !== props.knowledgeBase?.id) return;
        message.success('文件已删除');
        if (documents.value.length === 1 && page.value > 1) page.value -= 1;
        await refreshAllDocuments();
        emit('changed');
      } finally {
        deletingId.value = null;
      }
    },
  });
}
</script>
