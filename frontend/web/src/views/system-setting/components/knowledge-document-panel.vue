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
      <p class="text-muted-foreground mb-4 whitespace-pre-wrap break-words text-sm">
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
          @click="loadDocuments()"
        >
          刷新
        </NButton>
      </div>
      <NDataTable
        remote
        :columns="columns"
        :data="documents"
        :loading="loading"
        :pagination="false"
        :row-key="(row: KnowledgeDocument) => row.id"
        :scroll-x="760"
      />
      <div v-if="total > 0" class="mt-4 flex justify-end">
        <NPagination
          :page="page"
          :page-size="pageSize"
          :item-count="total"
          :page-sizes="[10, 20, 50]"
          show-size-picker
          :disabled="loading || uploading"
          @update:page="changePage"
          @update:page-size="changePageSize"
        />
      </div>
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

import { h, ref, watch } from 'vue';

import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NTag,
  NUpload,
  NUploadDragger,
  NPagination,
} from 'naive-ui';

import { dialog, message } from '#/adapter/naive';
import {
  deleteKnowledgeDocumentApi,
  getKnowledgeDocumentsApi,
  uploadKnowledgeDocumentApi,
} from '#/api/knowledge';

const MAX_FILE_SIZE = 20 * 1024 * 1024;

const props = defineProps<{
  knowledgeBase: KnowledgeBase | null;
}>();

const emit = defineEmits<{
  changed: [];
  'uploading-change': [value: boolean];
}>();

const documents = ref<KnowledgeDocument[]>([]);
const fileList = ref<UploadFileInfo[]>([]);
const loading = ref(false);
const uploading = ref(false);
const deletingId = ref<null | number>(null);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
let loadSequence = 0;

const statusMeta: Record<
  KnowledgeDocumentStatus,
  { label: string; type: 'default' | 'error' | 'info' | 'success' | 'warning' }
> = {
  deleting: { label: '删除中', type: 'warning' },
  failed: { label: '处理失败', type: 'error' },
  processing: { label: '向量化中', type: 'info' },
  ready: { label: '已向量化', type: 'success' },
  uploaded: { label: '已上传（未向量化）', type: 'default' },
};

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
    key: 'status',
    title: '状态',
    minWidth: 160,
    render: (row) => {
      const meta = statusMeta[row.status];
      const label =
        row.status === 'deleting' && row.error_message
          ? '删除失败，可重试'
          : meta.label;
      return h('div', [
        h(NTag, { size: 'small', type: meta.type }, { default: () => label }),
        row.error_message
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
    width: 100,
    render: (row) =>
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
  },
];

watch(
  () => props.knowledgeBase?.id,
  () => {
    fileList.value = [];
    documents.value = [];
    total.value = 0;
    page.value = 1;
    void loadDocuments(1);
  },
  { immediate: true },
);

function formatSize(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
}

function formatTime(value: string) {
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

  uploading.value = true;
  emit('uploading-change', true);
  try {
    await uploadKnowledgeDocumentApi(knowledgeBaseId, options.file.file);
    options.onFinish();
    fileList.value = [];
    message.success('文件已上传，尚未向量化');
    page.value = 1;
    await loadDocuments(1);
    emit('changed');
  } catch {
    options.onError();
  } finally {
    uploading.value = false;
    emit('uploading-change', false);
  }
}

async function loadDocuments(requestedPage = page.value) {
  const knowledgeBaseId = props.knowledgeBase?.id;
  const sequence = ++loadSequence;
  if (!knowledgeBaseId) {
    documents.value = [];
    total.value = 0;
    return;
  }
  loading.value = true;
  try {
    const result = await getKnowledgeDocumentsApi(knowledgeBaseId, {
      page: requestedPage,
      page_size: pageSize.value,
    });
    if (sequence !== loadSequence || knowledgeBaseId !== props.knowledgeBase?.id)
      return;
    if (result.items.length === 0 && result.page > 1 && result.total > 0) {
      page.value = result.page - 1;
      await loadDocuments(page.value);
      return;
    }
    documents.value = result.items;
    total.value = result.total;
    page.value = result.page;
  } finally {
    if (sequence === loadSequence) loading.value = false;
  }
}

function changePage(value: number) {
  page.value = value;
  void loadDocuments(value);
}

function changePageSize(value: number) {
  pageSize.value = value;
  page.value = 1;
  void loadDocuments(1);
}

function confirmDelete(document: KnowledgeDocument) {
  dialog.warning({
    title: document.status === 'deleting' ? '重试删除文件' : '删除文件',
    content: `确认删除“${document.original_name}”吗？原文和数据库记录将同时清理。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      const knowledgeBaseId = props.knowledgeBase?.id;
      if (!knowledgeBaseId) return;
      deletingId.value = document.id;
      try {
        await deleteKnowledgeDocumentApi(knowledgeBaseId, document.id);
        message.success('文件已删除');
        if (documents.value.length === 1 && page.value > 1) page.value -= 1;
        await loadDocuments();
        emit('changed');
      } finally {
        deletingId.value = null;
      }
    },
  });
}
</script>
