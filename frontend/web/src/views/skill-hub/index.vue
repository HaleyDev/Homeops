<template>
  <div class="p-5">
    <div class="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold">Skill Hub</h1>
        <p class="text-muted-foreground mt-2 text-sm">
          集中管理 Agent Skills，支持上传、版本管理、标签筛选和下载
        </p>
      </div>
      <div class="flex gap-2">
        <NButton type="primary" @click="openUpload">上传 Skill</NButton>
        <NButton
          type="primary"
          :disabled="selectedSkills.size === 0"
          @click="promptVisible = true"
        >
          生成安装提示语
        </NButton>
      </div>
    </div>

    <NCard>
      <template #header>Skill 列表</template>
      <template #header-extra>
        <NButton text size="small" :loading="loading" @click="refreshAll">
          刷新
        </NButton>
      </template>

      <div class="mb-4 grid gap-3 md:grid-cols-2">
        <NInput
          v-model:value="keyword"
          clearable
          placeholder="搜索名称或发布版本描述"
          @keyup.enter="searchNow"
        />
        <NSelect
          v-model:value="filterTags"
          multiple
          clearable
          filterable
          :options="tagOptions"
          placeholder="按标签筛选（多选取交集）"
        />
      </div>

      <NDataTable
        remote
        :checked-row-keys="checkedRowKeys"
        :columns="columns"
        :data="skills"
        :loading="loading"
        :pagination="pagination"
        :row-key="(row: Skill) => row.id"
        :scroll-x="1180"
        @update:checked-row-keys="updateSelection"
        @update:page="changePage"
        @update:page-size="changePageSize"
      />
    </NCard>

    <NModal v-model:show="uploadModalVisible">
      <SkillUploadPanel
        ref="uploadPanel"
        :tag-options="tagOptions"
        style="width: min(680px, 92vw); max-height: 88vh; overflow-y: auto"
        @close="uploadModalVisible = false"
        @uploaded="handleUploaded"
      />
    </NModal>

    <SkillVersionDrawer
      v-model:show="versionDrawerVisible"
      :skill="activeSkill"
      @changed="handleVersionsChanged"
      @upload-new="startNewVersion"
    />

    <NModal
      v-model:show="editModalVisible"
      preset="card"
      title="编辑 Skill"
      style="width: min(560px, 92vw)"
    >
      <div v-if="editingSkill" class="mb-4 space-y-2 text-sm">
        <div>
          <span class="text-muted-foreground">name：</span>
          <span class="font-mono">{{ editingSkill.name }}</span>
        </div>
        <div>
          <span class="text-muted-foreground">发布版本描述：</span>
          {{ editingSkill.description }}
        </div>
      </div>
      <label class="mb-2 block text-sm font-medium">标签</label>
      <NSelect
        v-model:value="editTags"
        multiple
        filterable
        tag
        clearable
        :disabled="savingEdit"
        :options="tagOptions"
        placeholder="选择或输入标签，最多 20 个"
      />
      <div class="text-muted-foreground mt-2 text-xs">
        name 和 description 由发布版本的 SKILL.md 决定，此处仅修改标签。
      </div>
      <NAlert v-if="editError" type="error" class="mt-4">
        {{ editError }}
      </NAlert>
      <div class="mt-5 flex justify-end gap-2">
        <NButton :disabled="savingEdit" @click="editModalVisible = false">
          取消
        </NButton>
        <NButton
          type="primary"
          :disabled="Boolean(editTagError)"
          :loading="savingEdit"
          @click="saveSkillEdit"
        >
          保存
        </NButton>
      </div>
    </NModal>

    <NModal
      v-model:show="promptVisible"
      preset="card"
      title="Agent 安装提示语"
      style="width: min(780px, 92vw)"
    >
      <NAlert type="warning" class="mb-4" :bordered="false">
        源地址使用当前访问地址。如果 Agent
        的执行环境无法访问该地址，请替换为实际可访问的地址。
      </NAlert>
      <NInput
        :value="installPrompt"
        type="textarea"
        readonly
        :rows="18"
        class="font-mono text-xs"
      />
      <div class="mt-4 flex items-center justify-between gap-3">
        <span class="text-muted-foreground text-sm">
          已选择 {{ selectedSkills.size }} 个 Skill
        </span>
        <NButton type="primary" @click="copyPrompt">一键复制</NButton>
      </div>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import type { DataTableColumns, DataTableRowKey } from 'naive-ui';

import type { Skill, SkillTag } from '#/api/skill-hub';

import {
  computed,
  h,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue';

import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NInput,
  NModal,
  NSelect,
  NTag,
} from 'naive-ui';

import { dialog, message } from '#/adapter/naive';
import {
  deleteSkillApi,
  getSkillsApi,
  getSkillTagsApi,
  updateSkillApi,
} from '#/api/skill-hub';

import SkillUploadPanel from './components/skill-upload-panel.vue';
import SkillVersionDrawer from './components/skill-version-drawer.vue';
import {
  buildInstallPrompt,
  extractSkillUploadErrors,
  formatSkillSize,
  formatSkillSourceType,
  formatSkillTime,
  validateSkillTags,
} from './skill-hub-utils';

const skills = ref<Skill[]>([]);
const tags = ref<SkillTag[]>([]);
const keyword = ref('');
const filterTags = ref<string[]>([]);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const selectedSkills = ref<Map<number, Skill>>(new Map());
const promptVisible = ref(false);
const uploadModalVisible = ref(false);
const editModalVisible = ref(false);
const editingSkill = ref<Skill | null>(null);
const editTags = ref<string[]>([]);
const editError = ref('');
const savingEdit = ref(false);
const versionDrawerVisible = ref(false);
const activeSkill = ref<Skill | null>(null);
const uploadPanel = ref<InstanceType<typeof SkillUploadPanel> | null>(null);
const deletingId = ref<null | number>(null);
let loadSequence = 0;
let searchTimer: ReturnType<typeof setTimeout> | undefined;

const tagOptions = computed(() =>
  tags.value.map((tag) => ({
    label: `${tag.name}（${tag.count}）`,
    value: tag.name,
  })),
);
const checkedRowKeys = computed<DataTableRowKey[]>(() => [
  ...selectedSkills.value.keys(),
]);
const selectedSkillList = computed(() =>
  [...selectedSkills.value.values()].toSorted((left, right) =>
    left.name.localeCompare(right.name),
  ),
);
const installPrompt = computed(() =>
  buildInstallPrompt(selectedSkillList.value, window.location.origin),
);
const editTagError = computed(() => validateSkillTags(editTags.value));
const pagination = computed(() => ({
  itemCount: total.value,
  page: page.value,
  pageSize: pageSize.value,
  pageSizes: [10, 20, 50, 100],
  showSizePicker: true,
}));

const statusLabels: Record<Skill['status'], string> = {
  deleting: '删除中',
  empty: '无可用版本',
  ready: '已发布',
};

const columns: DataTableColumns<Skill> = [
  {
    type: 'selection',
    disabled: (row) => row.status !== 'ready',
  },
  {
    key: 'name',
    title: 'Skill',
    minWidth: 180,
    render: (row) =>
      h('div', [
        h('div', { class: 'break-all font-medium' }, row.name),
        h(
          'div',
          { class: 'text-muted-foreground mt-1 font-mono text-xs' },
          row.current_version ?? '无发布版本',
        ),
      ]),
  },
  {
    key: 'source_type',
    title: '类型',
    width: 140,
    render: (row) => formatSkillSourceType(row.source_type),
  },
  {
    key: 'description',
    title: '发布版本描述',
    ellipsis: { tooltip: true },
    minWidth: 220,
  },
  {
    key: 'tags',
    title: '标签',
    minWidth: 150,
    render: (row) =>
      row.tags.length > 0
        ? h(
            'div',
            { class: 'flex flex-wrap gap-1' },
            row.tags.map((tag) =>
              h(NTag, { key: tag, size: 'small' }, { default: () => tag }),
            ),
          )
        : '—',
  },
  {
    key: 'owner',
    title: '上传者',
    width: 110,
    render: (row) => row.owner?.username ?? '—',
  },
  {
    key: 'version_count',
    title: '版本数',
    width: 80,
  },
  {
    key: 'size_bytes',
    title: '大小',
    width: 100,
    render: (row) => formatSkillSize(row.size_bytes),
  },
  {
    key: 'status',
    title: '状态',
    width: 100,
    render: (row) =>
      h(
        NTag,
        {
          size: 'small',
          type: row.status === 'ready' ? 'success' : 'warning',
        },
        { default: () => statusLabels[row.status] },
      ),
  },
  {
    key: 'updated_at',
    title: '更新时间',
    width: 170,
    render: (row) => formatSkillTime(row.updated_at),
  },
  {
    key: 'actions',
    title: '操作',
    fixed: 'right',
    width: 210,
    render: (row) =>
      h('div', { class: 'flex flex-wrap gap-2' }, [
        h(
          NButton,
          {
            size: 'small',
            text: true,
            type: 'primary',
            onClick: () => openVersions(row),
          },
          { default: () => '版本管理' },
        ),
        row.download_path
          ? h(
              NButton,
              {
                size: 'small',
                text: true,
                type: 'primary',
                onClick: () => downloadSkill(row),
              },
              { default: () => '下载' },
            )
          : null,
        row.can_manage
          ? h(
              NButton,
              {
                size: 'small',
                text: true,
                type: 'primary',
                onClick: () => openEdit(row),
              },
              { default: () => '编辑' },
            )
          : null,
        row.can_manage
          ? h(
              NButton,
              {
                disabled: deletingId.value !== null,
                loading: deletingId.value === row.id,
                size: 'small',
                text: true,
                type: 'error',
                onClick: () => confirmDelete(row),
              },
              { default: () => '删除' },
            )
          : null,
      ]),
  },
];

watch(keyword, scheduleSearch);
watch(filterTags, () => {
  page.value = 1;
  void loadSkills();
});

onMounted(() => {
  void refreshAll();
});
onBeforeUnmount(() => {
  clearTimeout(searchTimer);
  loadSequence += 1;
});

async function loadSkills() {
  const sequence = ++loadSequence;
  loading.value = true;
  try {
    const result = await getSkillsApi({
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      page_size: pageSize.value,
      tags: filterTags.value,
    });
    if (sequence !== loadSequence) return;
    if (result.items.length === 0 && result.page > 1 && result.total > 0) {
      page.value = result.page - 1;
      await loadSkills();
      return;
    }
    skills.value = result.items;
    page.value = result.page;
    total.value = result.total;
    const nextSelection = new Map(selectedSkills.value);
    for (const item of result.items) {
      if (!nextSelection.has(item.id)) continue;
      if (item.status === 'ready') nextSelection.set(item.id, item);
      else nextSelection.delete(item.id);
    }
    selectedSkills.value = nextSelection;
    if (activeSkill.value) {
      activeSkill.value =
        result.items.find((item) => item.id === activeSkill.value?.id) ??
        activeSkill.value;
    }
  } finally {
    if (sequence === loadSequence) loading.value = false;
  }
}

async function loadTags() {
  const result = await getSkillTagsApi();
  tags.value = result.items;
}

async function refreshAll() {
  await Promise.all([loadSkills(), loadTags()]);
}

function scheduleSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    page.value = 1;
    void loadSkills();
  }, 350);
}

function searchNow() {
  clearTimeout(searchTimer);
  page.value = 1;
  void loadSkills();
}

function changePage(value: number) {
  page.value = value;
  void loadSkills();
}

function changePageSize(value: number) {
  pageSize.value = value;
  page.value = 1;
  void loadSkills();
}

function updateSelection(keys: DataTableRowKey[]) {
  const keySet = new Set(keys.map(Number));
  const next = new Map(selectedSkills.value);
  for (const row of skills.value) {
    if (keySet.has(row.id) && row.status === 'ready') next.set(row.id, row);
    else next.delete(row.id);
  }
  selectedSkills.value = next;
}

function openUpload() {
  uploadModalVisible.value = true;
  void nextTick(() => uploadPanel.value?.clearAll());
}

async function handleUploaded(name: string) {
  uploadModalVisible.value = false;
  keyword.value = '';
  filterTags.value = [];
  page.value = 1;
  clearTimeout(searchTimer);
  await refreshAll();
  const uploaded = skills.value.find((item) => item.name === name);
  if (uploaded) activeSkill.value = uploaded;
}

function openVersions(skill: Skill) {
  activeSkill.value = skill;
  versionDrawerVisible.value = true;
}

function openEdit(skill: Skill) {
  if (!skill.can_manage) return;
  editingSkill.value = skill;
  editTags.value = [...skill.tags];
  editError.value = '';
  editModalVisible.value = true;
}

async function saveSkillEdit() {
  const skill = editingSkill.value;
  if (!skill || editTagError.value || savingEdit.value) return;
  savingEdit.value = true;
  editError.value = '';
  try {
    const tags = editTags.value.map((tag) => tag.trim());
    const updated = await updateSkillApi(skill.name, tags);
    editingSkill.value = updated;
    editModalVisible.value = false;
    message.success('Skill 标签已更新');
    await refreshAll();
  } catch (error) {
    const errors = extractSkillUploadErrors(error);
    editError.value = errors.join('；') || '标签保存失败，请稍后重试';
  } finally {
    savingEdit.value = false;
  }
}

async function handleVersionsChanged(skillDeleted: boolean) {
  if (activeSkill.value && skillDeleted) {
    const next = new Map(selectedSkills.value);
    next.delete(activeSkill.value.id);
    selectedSkills.value = next;
    activeSkill.value = null;
    versionDrawerVisible.value = false;
  }
  await refreshAll();
}

function startNewVersion(skill: Skill) {
  versionDrawerVisible.value = false;
  uploadModalVisible.value = true;
  void nextTick(() => uploadPanel.value?.startNewVersion(skill));
}

function downloadSkill(skill: Skill) {
  if (skill.download_path) {
    window.open(skill.download_path, '_blank', 'noopener');
  }
}

function confirmDelete(skill: Skill) {
  if (!skill.can_manage) return;
  dialog.warning({
    title: '删除 Skill',
    content: `确认删除“${skill.name}”及其全部版本吗？发现索引和下载地址将立即失效。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      deletingId.value = skill.id;
      try {
        await deleteSkillApi(skill.name);
        const next = new Map(selectedSkills.value);
        next.delete(skill.id);
        selectedSkills.value = next;
        if (activeSkill.value?.id === skill.id) {
          activeSkill.value = null;
          versionDrawerVisible.value = false;
        }
        if (skills.value.length === 1 && page.value > 1) page.value -= 1;
        message.success('Skill 已删除');
        await refreshAll();
      } finally {
        deletingId.value = null;
      }
    },
  });
}

function copyWithExecCommand(text: string) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.readOnly = true;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '0';
  document.body.append(textarea);
  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    textarea.remove();
  }
}

async function copyPrompt() {
  let copied = false;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(installPrompt.value);
      copied = true;
    } catch {
      copied = false;
    }
  }
  if (!copied) copied = copyWithExecCommand(installPrompt.value);
  if (copied) {
    message.success('安装提示语已复制');
  } else {
    message.error('复制失败，请手动选择文本复制');
  }
}
</script>
