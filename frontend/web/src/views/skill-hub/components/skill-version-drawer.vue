<template>
  <NDrawer
    :show="show"
    width="min(1100px, 96vw)"
    placement="right"
    @update:show="emit('update:show', $event)"
  >
    <NDrawerContent
      :title="skill ? `${skill.name} · 版本管理` : '版本管理'"
      closable
    >
      <template #footer>
        <NButton
          v-if="skill?.can_manage"
          type="primary"
          size="small"
          @click="emit('upload-new', skill)"
        >
          上传新版本
        </NButton>
      </template>

      <NSpin :show="loading">
        <NDataTable
          :columns="columns"
          :data="versions"
          :loading="loading"
          :pagination="{ pageSize: 10 }"
          :row-key="(row: SkillVersion) => row.version"
          :scroll-x="1080"
        />
        <NEmpty
          v-if="!loading && versions.length === 0"
          description="暂无版本"
        />
      </NSpin>
    </NDrawerContent>
  </NDrawer>
</template>

<script setup lang="ts">
import type { DataTableColumns } from 'naive-ui';

import type { Skill, SkillVersion } from '#/api/skill-hub';

import { h, ref, watch } from 'vue';

import {
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NSpin,
  NTag,
} from 'naive-ui';

import { dialog, message } from '#/adapter/naive';
import {
  deleteSkillVersionApi,
  getSkillVersionsApi,
  publishSkillVersionApi,
} from '#/api/skill-hub';

import {
  formatSkillSize,
  formatSkillSourceType,
  formatSkillTime,
} from '../skill-hub-utils';

const props = defineProps<{
  show: boolean;
  skill: Skill | null;
}>();

const emit = defineEmits<{
  changed: [skillDeleted: boolean];
  'update:show': [value: boolean];
  'upload-new': [skill: Skill];
}>();

const versions = ref<SkillVersion[]>([]);
const loading = ref(false);
const deletingVersion = ref<null | string>(null);
const publishingVersion = ref<null | string>(null);
let loadSequence = 0;

const columns: DataTableColumns<SkillVersion> = [
  {
    key: 'version',
    title: '版本',
    minWidth: 150,
    render: (row) =>
      h('div', { class: 'flex items-center gap-2' }, [
        h('span', { class: 'font-mono' }, row.version),
        row.is_current
          ? h(
              NTag,
              { size: 'small', type: 'success' },
              { default: () => '发布版本' },
            )
          : null,
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
    title: '描述',
    ellipsis: { tooltip: true },
    minWidth: 200,
  },
  {
    key: 'uploaded_by',
    title: '上传者',
    width: 110,
    render: (row) => row.uploaded_by?.username ?? '—',
  },
  {
    key: 'size_bytes',
    title: '大小',
    width: 100,
    render: (row) => formatSkillSize(row.size_bytes),
  },
  {
    key: 'created_at',
    title: '上传时间',
    width: 170,
    render: (row) => formatSkillTime(row.created_at),
  },
  {
    key: 'actions',
    title: '操作',
    fixed: 'right',
    width: 210,
    render: (row) =>
      h('div', { class: 'flex flex-wrap gap-2' }, [
        !row.is_current && props.skill?.can_manage
          ? h(
              NButton,
              {
                disabled:
                  deletingVersion.value !== null ||
                  publishingVersion.value !== null,
                loading: publishingVersion.value === row.version,
                size: 'small',
                text: true,
                type: 'primary',
                onClick: () => confirmPublish(row),
              },
              { default: () => '发布' },
            )
          : null,
        h(
          NButton,
          {
            size: 'small',
            text: true,
            type: 'primary',
            onClick: () => downloadVersion(row),
          },
          { default: () => '下载' },
        ),
        props.skill?.can_manage
          ? h(
              NButton,
              {
                disabled:
                  deletingVersion.value !== null ||
                  publishingVersion.value !== null,
                loading: deletingVersion.value === row.version,
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

watch(
  () => [props.show, props.skill?.id] as const,
  ([show]) => {
    if (show && props.skill) void loadVersions();
    if (!show) {
      loadSequence += 1;
      versions.value = [];
    }
  },
  { immediate: true },
);

async function loadVersions() {
  const skill = props.skill;
  if (!skill) return;
  const sequence = ++loadSequence;
  loading.value = true;
  try {
    const result = await getSkillVersionsApi(skill.name);
    if (sequence !== loadSequence || props.skill?.id !== skill.id) return;
    versions.value = result.items;
  } finally {
    if (sequence === loadSequence) loading.value = false;
  }
}

function downloadVersion(version: SkillVersion) {
  window.open(version.download_path, '_blank', 'noopener');
}

function confirmPublish(version: SkillVersion) {
  const skill = props.skill;
  if (!skill?.can_manage || version.is_current) return;
  dialog.warning({
    title: '发布历史版本',
    content: `确认将“${skill.name}”的发布版本切换为 ${version.version} 吗？列表描述、Discovery 和默认下载将立即使用该版本。`,
    positiveText: '发布',
    negativeText: '取消',
    onPositiveClick: async () => {
      publishingVersion.value = version.version;
      try {
        await publishSkillVersionApi(skill.name, version.version);
        message.success(`已发布 ${version.version}`);
        await loadVersions();
        emit('changed', false);
      } finally {
        publishingVersion.value = null;
      }
    },
  });
}

function confirmDelete(version: SkillVersion) {
  const skill = props.skill;
  if (!skill?.can_manage) return;
  dialog.warning({
    title: '删除 Skill 版本',
    content: `确认删除“${skill.name}”的 ${version.version} 版本吗？对应 ZIP 将一并删除。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      deletingVersion.value = version.version;
      try {
        await deleteSkillVersionApi(skill.name, version.version);
        const skillDeleted = versions.value.length === 1;
        message.success('版本已删除');
        if (skillDeleted) emit('update:show', false);
        emit('changed', skillDeleted);
        if (!skillDeleted) await loadVersions();
      } finally {
        deletingVersion.value = null;
      }
    },
  });
}
</script>
