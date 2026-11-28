<template>
  <NCard id="skill-upload-panel" closable @close="emit('close')">
    <template #header>上传 Skill</template>
    <template #header-extra>
      <NButton
        v-if="fileList.length > 0 || targetSkill"
        text
        size="small"
        :disabled="validating || uploading"
        @click="clearAll"
      >
        清除
      </NButton>
    </template>

    <NAlert
      v-if="targetSkill"
      type="info"
      class="mb-4"
      closable
      @close="clearTarget"
    >
      正在为“{{ targetSkill.name }}”上传新版本，当前发布版本为
      {{ targetSkill.current_version ?? '无' }}。
    </NAlert>

    <NUpload
      v-model:file-list="fileList"
      :max="1"
      accept=".md,.zip,.tar,.tar.gz,.tgz"
      :disabled="validating || uploading"
      :custom-request="customValidate"
      :before-upload="beforeUpload"
      @remove="handleRemove"
    >
      <NUploadDragger>
        <div class="py-5">
          <div class="mb-2 font-medium">
            {{
              validating
                ? '正在解析和校验文件'
                : '点击或拖拽选择单个 Skill 文件'
            }}
          </div>
          <div class="text-muted-foreground text-xs">
            支持 SKILL.md、ZIP、TAR、TAR.GZ、TGZ，最大 10 MiB
          </div>
        </div>
      </NUploadDragger>
    </NUpload>

    <NSpin :show="validating || lookupLoading">
      <div v-if="report" class="mt-5">
        <NAlert :type="report.valid ? 'success' : 'error'" :bordered="false">
          {{
            !report.valid
              ? '校验失败，请根据错误信息修改文件'
              : report.warnings.length > 0
                ? '校验通过，但有警告'
                : '校验通过'
          }}
        </NAlert>

        <dl
          class="mt-4 grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm"
        >
          <dt class="text-muted-foreground">name</dt>
          <dd class="break-all font-mono">{{ report.name || '未解析' }}</dd>
          <dt class="text-muted-foreground">description</dt>
          <dd class="whitespace-pre-wrap break-words">
            {{ report.description || '未解析' }}
          </dd>
          <dt class="text-muted-foreground">类型</dt>
          <dd>{{ formatSkillSourceType(report.source_type) }}</dd>
          <dt class="text-muted-foreground">文件数</dt>
          <dd>{{ report.file_count }}</dd>
          <dt class="text-muted-foreground">原始大小</dt>
          <dd>{{ formatSkillSize(report.size_bytes) }}</dd>
        </dl>

        <NAlert
          v-if="targetMismatch"
          type="error"
          class="mt-4"
          :bordered="false"
        >
          文件中的 name 为“{{ report.name }}”，必须保持为“{{
            targetSkill?.name
          }}”。
        </NAlert>

        <div v-if="report.errors.length > 0" class="mt-4">
          <div class="mb-2 text-sm font-medium text-error">字段错误</div>
          <ul class="list-disc space-y-1 pl-5 text-sm">
            <li
              v-for="issue in report.errors"
              :key="`${issue.field}-${issue.code}-${issue.message}`"
            >
              <span class="font-mono">{{ issue.field }}</span
              >：{{ issue.message }}
            </li>
          </ul>
        </div>
        <div
          v-if="report.warnings.length > 0"
          class="mt-4 text-sm text-warning"
        >
          <div
            v-for="issue in report.warnings"
            :key="`${issue.field}-${issue.code}`"
          >
            {{ issue.message }}
          </div>
        </div>
      </div>
    </NSpin>

    <NAlert
      v-if="existingSkill"
      :type="existingSkill.can_manage ? 'info' : 'error'"
      class="mt-4"
      :bordered="false"
    >
      <div>已存在 Skill“{{ existingSkill.name }}”，本次将追加新版本。</div>
      <div v-if="!existingSkill.can_manage" class="mt-1">
        你不是该 Skill 的上传者，不能上传新版本。
      </div>
      <div v-if="existingVersions.length > 0" class="mt-2 flex flex-wrap gap-1">
        <NTag v-for="item in existingVersions" :key="item.version" size="small">
          {{ item.version }}
        </NTag>
      </div>
    </NAlert>

    <div class="mt-5">
      <label class="mb-2 block text-sm font-medium" for="skill-version">
        版本号（必填）
      </label>
      <NInput
        id="skill-version"
        v-model:value="version"
        placeholder="例如 v1.0.0 或 release-20261128"
        :disabled="!report?.valid || validating || uploading"
      />
      <div v-if="versionError" class="mt-1 text-xs text-error">
        {{ versionError }}
      </div>
    </div>

    <div class="mt-4">
      <label class="mb-2 block text-sm font-medium">标签（可选）</label>
      <NSelect
        v-model:value="selectedTags"
        multiple
        filterable
        tag
        clearable
        :options="tagOptions"
        :disabled="!report?.valid || validating || uploading"
        placeholder="选择或输入标签，最多 20 个"
        @update:value="tagsTouched = true"
      />
      <div class="text-muted-foreground mt-1 text-xs">
        新版本未修改标签时保留原标签；清空后提交会移除全部标签。
      </div>
      <div v-if="tagError" class="mt-1 text-xs text-error">{{ tagError }}</div>
    </div>

    <NAlert v-if="formErrorMessages.length > 0" type="error" class="mt-4">
      <div v-for="error in formErrorMessages" :key="error">{{ error }}</div>
    </NAlert>

    <NButton
      type="primary"
      block
      class="mt-5"
      :disabled="!canSubmit"
      :loading="uploading"
      @click="submitUpload"
    >
      确认上传
    </NButton>
  </NCard>
</template>

<script setup lang="ts">
import type {
  UploadCustomRequestOptions,
  UploadFileInfo,
  UploadSettledFileInfo,
} from 'naive-ui';

import type {
  Skill,
  SkillValidationReport,
  SkillVersion,
} from '#/api/skill-hub';

import { computed, ref } from 'vue';

import {
  NAlert,
  NButton,
  NCard,
  NInput,
  NSelect,
  NSpin,
  NTag,
  NUpload,
  NUploadDragger,
} from 'naive-ui';

import { message } from '#/adapter/naive';
import {
  getSkillsApi,
  getSkillVersionsApi,
  uploadSkillApi,
  validateSkillApi,
} from '#/api/skill-hub';

import {
  extractSkillUploadErrors,
  formatSkillSize,
  formatSkillSourceType,
  validateSkillFile,
  validateSkillTags,
  validateSkillVersion,
} from '../skill-hub-utils';

const props = withDefaults(
  defineProps<{
    tagOptions?: Array<{ label: string; value: string }>;
  }>(),
  { tagOptions: () => [] },
);

const emit = defineEmits<{
  close: [];
  uploaded: [name: string];
}>();

const fileList = ref<UploadFileInfo[]>([]);
const selectedFile = ref<File | null>(null);
const report = ref<SkillValidationReport | null>(null);
const version = ref('');
const selectedTags = ref<string[]>([]);
const tagsTouched = ref(false);
const existingSkill = ref<Skill | null>(null);
const existingVersions = ref<SkillVersion[]>([]);
const targetSkill = ref<Skill | null>(null);
const validating = ref(false);
const lookupLoading = ref(false);
const uploading = ref(false);
const formErrorMessages = ref<string[]>([]);
let validationSequence = 0;

const targetMismatch = computed(() => {
  const targetName = targetSkill.value?.name;
  const reportName = report.value?.name;
  return Boolean(targetName && reportName && targetName !== reportName);
});
const versionError = computed(() =>
  version.value ? validateSkillVersion(version.value) : null,
);
const tagError = computed(() => validateSkillTags(selectedTags.value));
const canSubmit = computed(() =>
  Boolean(
    selectedFile.value &&
    report.value?.valid &&
    !targetMismatch.value &&
    !validateSkillVersion(version.value) &&
    !tagError.value &&
    !validating.value &&
    !lookupLoading.value &&
    !uploading.value &&
    (!existingSkill.value || existingSkill.value.can_manage),
  ),
);

function resetResult() {
  validationSequence += 1;
  selectedFile.value = null;
  report.value = null;
  version.value = '';
  existingSkill.value = targetSkill.value;
  existingVersions.value = [];
  selectedTags.value = [...(targetSkill.value?.tags ?? [])];
  tagsTouched.value = false;
  validating.value = false;
  lookupLoading.value = false;
  formErrorMessages.value = [];
}

function clearAll() {
  targetSkill.value = null;
  fileList.value = [];
  resetResult();
}

function handleRemove() {
  resetResult();
  return true;
}

function clearTarget() {
  targetSkill.value = null;
  existingSkill.value = null;
  existingVersions.value = [];
  selectedTags.value = [];
  tagsTouched.value = false;
  if (report.value?.valid && report.value.name) {
    void lookupExisting(report.value.name, validationSequence);
  }
}

function startNewVersion(skill: Skill) {
  targetSkill.value = skill;
  fileList.value = [];
  resetResult();
}

function beforeUpload({ file }: { file: UploadSettledFileInfo }) {
  const error = file.file ? validateSkillFile(file.file) : '无法读取所选文件';
  if (error) {
    message.error(error);
    return false;
  }
  return true;
}

async function customValidate(options: UploadCustomRequestOptions) {
  const file = options.file.file;
  const error = file ? validateSkillFile(file) : '无法读取所选文件';
  if (!file || error) {
    if (error) message.error(error);
    options.onError();
    return;
  }

  const sequence = ++validationSequence;
  selectedFile.value = file;
  report.value = null;
  version.value = '';
  existingSkill.value = targetSkill.value;
  existingVersions.value = [];
  selectedTags.value = [...(targetSkill.value?.tags ?? [])];
  tagsTouched.value = false;
  formErrorMessages.value = [];
  validating.value = true;
  let requestFailed = false;
  try {
    const result = await validateSkillApi(file);
    if (sequence !== validationSequence) return;
    report.value = result;
    if (result.valid && result.name) {
      await lookupExisting(result.name, sequence);
    }
  } catch {
    requestFailed = true;
    if (sequence === validationSequence) {
      formErrorMessages.value = ['文件校验请求失败，请重新选择后重试'];
    }
  } finally {
    if (sequence === validationSequence) validating.value = false;
    if (requestFailed) options.onError();
    else options.onFinish();
  }
}

async function lookupExisting(name: string, sequence: number) {
  lookupLoading.value = true;
  try {
    let existing = targetSkill.value;
    if (!existing) {
      const result = await getSkillsApi({
        keyword: name,
        page: 1,
        page_size: 100,
      });
      if (sequence !== validationSequence) return;
      existing = result.items.find((item) => item.name === name) ?? null;
    }
    existingSkill.value = existing;
    selectedTags.value = [...(existing?.tags ?? [])];
    tagsTouched.value = false;
    if (existing) {
      const versions = await getSkillVersionsApi(existing.name);
      if (sequence !== validationSequence) return;
      existingVersions.value = versions.items;
    }
  } catch {
    if (sequence === validationSequence) existingVersions.value = [];
  } finally {
    if (sequence === validationSequence) lookupLoading.value = false;
  }
}

async function submitUpload() {
  const file = selectedFile.value;
  const name = report.value?.name;
  if (!file || !name || !canSubmit.value) return;
  uploading.value = true;
  formErrorMessages.value = [];
  try {
    const tags =
      existingSkill.value && !tagsTouched.value
        ? undefined
        : selectedTags.value.map((tag) => tag.trim());
    await uploadSkillApi(file, version.value, tags);
    message.success(`Skill“${name}”的 ${version.value} 版本已上传`);
    clearAll();
    emit('uploaded', name);
  } catch (error) {
    const errors = extractSkillUploadErrors(error);
    formErrorMessages.value =
      errors.length > 0
        ? errors
        : ['上传失败，请检查版本号是否重复以及是否拥有管理权限'];
  } finally {
    uploading.value = false;
  }
}

defineExpose({ clearAll, startNewVersion });
</script>
