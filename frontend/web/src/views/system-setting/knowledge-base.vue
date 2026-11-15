<template>
  <div class="p-5">
    <div class="mb-6">
      <h1 class="text-2xl font-semibold">知识库设置</h1>
      <p class="text-muted-foreground mt-2 text-sm">管理知识库和原始文件</p>
    </div>

    <NAlert type="info" class="mb-5" :bordered="false">
      当前仅管理知识库原文，切片和向量化将在后续阶段接入。
    </NAlert>

    <div class="grid items-start gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
      <NCard>
        <template #header>知识库</template>
        <template #header-extra>
          <NButton
            type="primary"
            size="small"
            :disabled="documentUploading"
            @click="openCreate"
          >
            新建知识库
          </NButton>
        </template>

        <NInput
          v-model:value="keyword"
          clearable
          placeholder="搜索名称或说明，回车立即搜索"
          :disabled="documentUploading"
          @keyup.enter="searchNow"
        />

        <NSpin :show="loading" class="mt-4 min-h-24">
          <div v-if="knowledgeBases.length > 0" class="flex flex-col gap-3">
            <div
              v-for="item in knowledgeBases"
              :key="item.id"
              class="rounded-lg border p-3 transition-colors"
              :class="
                selectedId === item.id
                  ? 'border-primary bg-primary/5'
                  : 'border-border'
              "
            >
              <button
                type="button"
                class="w-full cursor-pointer text-left disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="documentUploading"
                @click="selectedId = item.id"
              >
                <div class="flex items-start justify-between gap-2">
                  <span class="break-words font-medium">{{ item.name }}</span>
                  <NTag size="small" :bordered="false">
                    {{ item.document_count }} 个文件
                  </NTag>
                </div>
                <p
                  class="text-muted-foreground mt-2 line-clamp-3 whitespace-pre-wrap break-words text-xs"
                >
                  {{ item.description }}
                </p>
              </button>
              <div class="mt-3 flex justify-end gap-2 border-t pt-2">
                <NButton
                  text
                  size="small"
                  type="primary"
                  :disabled="documentUploading"
                  @click="openEdit(item)"
                >
                  编辑
                </NButton>
                <NButton
                  text
                  size="small"
                  type="error"
                  :disabled="item.document_count > 0 || documentUploading"
                  :title="
                    item.document_count > 0 ? '请先删除知识库中的全部文件' : ''
                  "
                  @click="confirmDelete(item)"
                >
                  删除
                </NButton>
              </div>
            </div>
          </div>
          <NEmpty
            v-else-if="!loading"
            class="py-8"
            :description="keyword ? '没有匹配的知识库' : '暂无知识库，请先新建'"
          />
        </NSpin>

        <div v-if="total > pageSize" class="mt-4 flex justify-center">
          <NPagination
            :page="page"
            :page-size="pageSize"
            :item-count="total"
            :disabled="loading || documentUploading"
            @update:page="changePage"
          />
        </div>
      </NCard>

      <KnowledgeDocumentPanel
        :knowledge-base="selectedKnowledgeBase"
        @changed="refreshSelectedKnowledgeBase"
        @uploading-change="documentUploading = $event"
      />
    </div>

    <KnowledgeBaseFormModal
      v-model:show="modalVisible"
      :knowledge-base="editingKnowledgeBase"
      :saving="saving"
      @submit="saveKnowledgeBase"
    />
  </div>
</template>

<script setup lang="ts">
import type { KnowledgeBase, CreateKnowledgeBaseParams } from '#/api/knowledge';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NInput,
  NPagination,
  NSpin,
  NTag,
} from 'naive-ui';

import { dialog, message } from '#/adapter/naive';
import {
  createKnowledgeBaseApi,
  deleteKnowledgeBaseApi,
  getKnowledgeBaseApi,
  getKnowledgeBasesApi,
  updateKnowledgeBaseApi,
} from '#/api/knowledge';

import KnowledgeBaseFormModal from './components/knowledge-base-form-modal.vue';
import KnowledgeDocumentPanel from './components/knowledge-document-panel.vue';

const knowledgeBases = ref<KnowledgeBase[]>([]);
const selectedId = ref<null | number>(null);
const keyword = ref('');
const loading = ref(false);
const saving = ref(false);
const documentUploading = ref(false);
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const modalVisible = ref(false);
const editingKnowledgeBase = ref<KnowledgeBase | null>(null);
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let loadSequence = 0;

const selectedKnowledgeBase = computed(
  () =>
    knowledgeBases.value.find((knowledgeBase) => knowledgeBase.id === selectedId.value) ??
    null,
);

watch(keyword, () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    page.value = 1;
    void loadKnowledgeBases();
  }, 350);
});

onMounted(() => loadKnowledgeBases());
onBeforeUnmount(() => clearTimeout(searchTimer));

async function loadKnowledgeBases(preferredId?: number) {
  const sequence = ++loadSequence;
  loading.value = true;
  try {
    const result = await getKnowledgeBasesApi({
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      page_size: pageSize,
    });
    if (sequence !== loadSequence) return;
    if (result.items.length === 0 && result.page > 1 && result.total > 0) {
      page.value = result.page - 1;
      await loadKnowledgeBases(preferredId);
      return;
    }
    knowledgeBases.value = result.items;
    total.value = result.total;
    page.value = result.page;
    const desiredId = preferredId ?? selectedId.value;
    selectedId.value = result.items.some((item) => item.id === desiredId)
      ? desiredId!
      : (result.items[0]?.id ?? null);
  } finally {
    if (sequence === loadSequence) loading.value = false;
  }
}

function searchNow() {
  clearTimeout(searchTimer);
  page.value = 1;
  void loadKnowledgeBases();
}

function changePage(value: number) {
  page.value = value;
  void loadKnowledgeBases();
}

function openCreate() {
  editingKnowledgeBase.value = null;
  modalVisible.value = true;
}

function openEdit(knowledgeBase: KnowledgeBase) {
  editingKnowledgeBase.value = knowledgeBase;
  modalVisible.value = true;
}

async function saveKnowledgeBase(value: CreateKnowledgeBaseParams) {
  saving.value = true;
  const editingId = editingKnowledgeBase.value?.id;
  try {
    const saved = editingId
      ? await updateKnowledgeBaseApi(editingId, value)
      : await createKnowledgeBaseApi(value);
    message.success(editingId ? '知识库已更新' : '知识库已创建');
    modalVisible.value = false;
    if (!editingId) {
      keyword.value = '';
      page.value = 1;
    }
    await loadKnowledgeBases(saved.id);
  } finally {
    saving.value = false;
  }
}

function confirmDelete(knowledgeBase: KnowledgeBase) {
  if (knowledgeBase.document_count > 0) return;
  dialog.warning({
    title: '删除知识库',
    content: `确认删除空知识库“${knowledgeBase.name}”吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await deleteKnowledgeBaseApi(knowledgeBase.id);
      message.success('知识库已删除');
      if (knowledgeBases.value.length === 1 && page.value > 1) page.value -= 1;
      if (selectedId.value === knowledgeBase.id) selectedId.value = null;
      await loadKnowledgeBases();
    },
  });
}

async function refreshSelectedKnowledgeBase() {
  if (!selectedId.value) return;
  const refreshed = await getKnowledgeBaseApi(selectedId.value);
  knowledgeBases.value = knowledgeBases.value.map((item) =>
    item.id === refreshed.id ? refreshed : item,
  );
}
</script>
