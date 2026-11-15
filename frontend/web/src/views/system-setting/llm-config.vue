<template>
  <div class="p-5">
    <div class="mb-6">
      <h1 class="text-2xl font-semibold">模型供应商配置</h1>
      <p class="text-muted-foreground mt-2 text-sm">
        管理全局供应商和模型，配置变更从下一轮对话开始生效
      </p>
    </div>

    <NCard title="当前选择" class="mb-5">
      <div class="flex flex-col gap-3 md:flex-row md:items-end">
        <div class="flex-1">
          <div class="mb-2 text-sm font-medium">文本模型</div>
          <NSelect
            v-model:value="selectedModelId"
            :options="selectableTextModels"
            :loading="loading"
            clearable
            filterable
            placeholder="请选择已启用的文本模型"
          />
        </div>
        <div class="flex gap-2">
          <NButton
            type="primary"
            :loading="saving"
            :disabled="!selectedModelId"
            @click="saveSelection"
          >
            保存选择
          </NButton>
          <NButton :disabled="!textSelection?.model" @click="clearSelection">
            取消当前选择
          </NButton>
        </div>
      </div>
      <div class="text-muted-foreground mt-3 text-xs">
        Embedding 配置能力已在接口中预留，本期页面仅开放文本模型选择。
      </div>
    </NCard>

    <NCard title="供应商管理" class="mb-5">
      <template #header-extra>
        <NButton type="primary" @click="openProviderCreate">新增供应商</NButton>
      </template>
      <NDataTable
        :columns="providerColumns"
        :data="providers"
        :loading="loading"
        :pagination="{ pageSize: 10 }"
        :scroll-x="1000"
      />
    </NCard>

    <NCard title="模型管理">
      <template #header-extra>
        <NButton
          type="primary"
          :disabled="providers.length === 0"
          @click="openModelCreate"
        >
          新增模型
        </NButton>
      </template>
      <NDataTable
        :columns="modelColumns"
        :data="models"
        :loading="loading"
        :pagination="{ pageSize: 10 }"
        :scroll-x="1100"
      />
    </NCard>

    <NModal
      v-model:show="providerModalVisible"
      preset="card"
      :title="providerForm.id ? '编辑供应商' : '新增供应商'"
      style="width: min(640px, calc(100vw - 32px))"
    >
      <NForm
        ref="providerFormRef"
        :model="providerForm"
        :rules="providerRules"
        label-placement="top"
      >
        <div class="grid gap-x-4 md:grid-cols-2">
          <NFormItem label="展示名称" path="name">
            <NInput
              v-model:value="providerForm.name"
              placeholder="例如：火山引擎"
            />
          </NFormItem>
          <NFormItem label="稳定内部标识" path="slug">
            <NInput
              v-model:value="providerForm.slug"
              :disabled="!!providerForm.id"
              placeholder="例如：volcengine"
            />
          </NFormItem>
        </div>
        <NFormItem label="API 根地址" path="base_url">
          <NInput
            v-model:value="providerForm.base_url"
            placeholder="https://example.com/v1"
          />
        </NFormItem>
        <NFormItem label="协议">
          <NInput value="OpenAI 兼容接口" disabled />
        </NFormItem>
        <NFormItem label="API Key">
          <NInput
            v-model:value="providerForm.api_key"
            type="password"
            show-password-on="click"
            :disabled="providerForm.clear_api_key"
            :placeholder="
              providerForm.id ? '留空保持原 Key 不变' : '请输入 API Key'
            "
          />
        </NFormItem>
        <NFormItem v-if="providerForm.id" label="清除已保存的 API Key">
          <NSwitch v-model:value="providerForm.clear_api_key" />
        </NFormItem>
        <NFormItem label="非敏感扩展配置（JSON）">
          <NInput
            v-model:value="providerForm.extraConfigText"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
          />
        </NFormItem>
        <NFormItem label="启用供应商">
          <NSwitch v-model:value="providerForm.is_active" />
        </NFormItem>
      </NForm>
      <template #footer>
        <div class="flex justify-end gap-2">
          <NButton @click="providerModalVisible = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="saveProvider">
保存
</NButton>
        </div>
      </template>
    </NModal>

    <NModal
      v-model:show="modelModalVisible"
      preset="card"
      :title="modelForm.id ? '编辑模型' : '新增模型'"
      style="width: min(640px, calc(100vw - 32px))"
    >
      <NForm
        ref="modelFormRef"
        :model="modelForm"
        :rules="modelRules"
        label-placement="top"
      >
        <NFormItem label="所属供应商" path="provider">
          <NSelect
            v-model:value="modelForm.provider"
            :options="providerOptions"
            placeholder="请选择供应商"
          />
        </NFormItem>
        <div class="grid gap-x-4 md:grid-cols-2">
          <NFormItem label="展示名称" path="display_name">
            <NInput
              v-model:value="modelForm.display_name"
              placeholder="例如：GLM 文本模型"
            />
          </NFormItem>
          <NFormItem label="真实模型标识" path="model_key">
            <NInput
              v-model:value="modelForm.model_key"
              placeholder="调用 API 使用的模型 ID"
            />
          </NFormItem>
        </div>
        <NFormItem label="模型用途">
          <NInput value="文本模型" disabled />
        </NFormItem>
        <NFormItem label="非敏感模型参数（JSON）">
          <NInput
            v-model:value="modelForm.parametersText"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
            placeholder="{&quot;temperature&quot;: 0.7}"
          />
        </NFormItem>
        <NFormItem label="启用模型">
          <NSwitch v-model:value="modelForm.is_active" />
        </NFormItem>
      </NForm>
      <template #footer>
        <div class="flex justify-end gap-2">
          <NButton @click="modelModalVisible = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="saveModel">
保存
</NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import type { DataTableColumns, FormInst, FormRules } from 'naive-ui';

import type { LLMModel, LLMProvider, LLMSelection } from '#/api/system-setting';

import { computed, h, onMounted, reactive, ref } from 'vue';

import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSelect,
  NSwitch,
  NTag,
} from 'naive-ui';

import { dialog, message } from '#/adapter/naive';
import {
  clearLLMSelectionApi,
  createLLMModelApi,
  createLLMProviderApi,
  deleteLLMModelApi,
  deleteLLMProviderApi,
  getLLMModelsApi,
  getLLMProvidersApi,
  getLLMSelectionsApi,
  selectLLMModelApi,
  updateLLMModelApi,
  updateLLMProviderApi,
} from '#/api/system-setting';

const loading = ref(false);
const saving = ref(false);
const providers = ref<LLMProvider[]>([]);
const models = ref<LLMModel[]>([]);
const selections = ref<LLMSelection[]>([]);
const selectedModelId = ref<null | number>(null);

const providerModalVisible = ref(false);
const modelModalVisible = ref(false);
const providerFormRef = ref<FormInst | null>(null);
const modelFormRef = ref<FormInst | null>(null);

const providerForm = reactive({
  api_key: '',
  base_url: '',
  clear_api_key: false,
  extraConfigText: '{}',
  id: null as null | number,
  is_active: true,
  name: '',
  protocol: 'openai_compatible' as const,
  slug: '',
});

const modelForm = reactive({
  display_name: '',
  id: null as null | number,
  is_active: true,
  model_key: '',
  model_type: 'text' as const,
  parametersText: '{}',
  provider: null as null | number,
});

const providerRules: FormRules = {
  base_url: { message: '请输入 API 根地址', required: true, trigger: 'blur' },
  name: { message: '请输入供应商名称', required: true, trigger: 'blur' },
  slug: { message: '请输入稳定内部标识', required: true, trigger: 'blur' },
};

const modelRules: FormRules = {
  display_name: { message: '请输入展示名称', required: true, trigger: 'blur' },
  model_key: { message: '请输入真实模型标识', required: true, trigger: 'blur' },
  provider: {
    message: '请选择供应商',
    required: true,
    trigger: ['blur', 'change'],
    type: 'number',
  },
};

const providerOptions = computed(() =>
  providers.value.map((provider) => ({
    label: `${provider.name}${provider.is_active ? '' : '（已停用）'}`,
    value: provider.id,
  })),
);

const textSelection = computed(() =>
  selections.value.find((selection) => selection.category === 'text'),
);

const selectableTextModels = computed(() => {
  const activeProviderIds = new Set(
    providers.value
      .filter((provider) => provider.is_active)
      .map((provider) => provider.id),
  );
  return models.value
    .filter(
      (model) =>
        model.model_type === 'text' &&
        model.is_active &&
        activeProviderIds.has(model.provider),
    )
    .map((model) => ({
      label: `${model.provider_name} / ${model.display_name}（${model.model_key}）`,
      value: model.id,
    }));
});

const providerColumns: DataTableColumns<LLMProvider> = [
  { key: 'name', title: '名称' },
  { key: 'slug', title: '内部标识' },
  { key: 'base_url', title: 'API 根地址', ellipsis: { tooltip: true } },
  {
    key: 'api_key_configured',
    title: 'API Key',
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.api_key_configured ? 'success' : 'warning' },
        { default: () => (row.api_key_configured ? '已配置' : '未配置') },
      ),
  },
  {
    key: 'is_active',
    title: '状态',
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.is_active ? 'success' : 'default' },
        { default: () => (row.is_active ? '启用' : '停用') },
      ),
  },
  {
    key: 'actions',
    title: '操作',
    width: 140,
    render: (row) =>
      h('div', { class: 'flex gap-2' }, [
        h(
          NButton,
          {
            size: 'small',
            text: true,
            type: 'primary',
            onClick: () => openProviderEdit(row),
          },
          { default: () => '编辑' },
        ),
        h(
          NButton,
          {
            size: 'small',
            text: true,
            type: 'error',
            onClick: () => confirmProviderDelete(row),
          },
          { default: () => '删除' },
        ),
      ]),
  },
];

const modelColumns: DataTableColumns<LLMModel> = [
  { key: 'display_name', title: '展示名称' },
  { key: 'provider_name', title: '供应商' },
  { key: 'model_key', title: '模型标识', ellipsis: { tooltip: true } },
  {
    key: 'model_type',
    title: '用途',
    render: (row) =>
      row.model_type === 'text' ? '文本模型' : 'Embedding 模型',
  },
  {
    key: 'selected_for',
    title: '当前选择',
    render: (row) =>
      row.selected_for
        ? h(
            NTag,
            { size: 'small', type: 'success' },
            { default: () => '当前文本模型' },
          )
        : '—',
  },
  {
    key: 'is_active',
    title: '状态',
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.is_active ? 'success' : 'default' },
        { default: () => (row.is_active ? '启用' : '停用') },
      ),
  },
  {
    key: 'actions',
    title: '操作',
    width: 140,
    render: (row) =>
      h('div', { class: 'flex gap-2' }, [
        h(
          NButton,
          {
            size: 'small',
            text: true,
            type: 'primary',
            onClick: () => openModelEdit(row),
          },
          { default: () => '编辑' },
        ),
        h(
          NButton,
          {
            size: 'small',
            text: true,
            type: 'error',
            onClick: () => confirmModelDelete(row),
          },
          { default: () => '删除' },
        ),
      ]),
  },
];

function parseObject(text: string) {
  let value: unknown;
  try {
    value = JSON.parse(text || '{}');
  } catch {
    throw new Error('Invalid JSON configuration.');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Configuration must be a JSON object.');
  }
  return value as Record<string, unknown>;
}

async function loadData() {
  loading.value = true;
  try {
    [providers.value, models.value, selections.value] = await Promise.all([
      getLLMProvidersApi(),
      getLLMModelsApi(),
      getLLMSelectionsApi(),
    ]);
    selectedModelId.value = textSelection.value?.model?.id ?? null;
  } finally {
    loading.value = false;
  }
}

function openProviderCreate() {
  Object.assign(providerForm, {
    api_key: '',
    base_url: '',
    clear_api_key: false,
    extraConfigText: '{}',
    id: null,
    is_active: true,
    name: '',
    protocol: 'openai_compatible',
    slug: '',
  });
  providerModalVisible.value = true;
}

function openProviderEdit(provider: LLMProvider) {
  Object.assign(providerForm, {
    api_key: '',
    base_url: provider.base_url,
    clear_api_key: false,
    extraConfigText: JSON.stringify(provider.extra_config, null, 2),
    id: provider.id,
    is_active: provider.is_active,
    name: provider.name,
    protocol: provider.protocol,
    slug: provider.slug,
  });
  providerModalVisible.value = true;
}

async function saveProvider() {
  await providerFormRef.value?.validate();
  if (!providerForm.id && !providerForm.api_key) {
    message.error('新建供应商必须配置 API Key');
    return;
  }
  saving.value = true;
  try {
    const payload = {
      base_url: providerForm.base_url,
      clear_api_key: providerForm.clear_api_key,
      extra_config: parseObject(providerForm.extraConfigText),
      is_active: providerForm.is_active,
      name: providerForm.name,
      protocol: providerForm.protocol,
      slug: providerForm.slug,
      ...(providerForm.api_key ? { api_key: providerForm.api_key } : {}),
    };
    providerForm.id
      ? await updateLLMProviderApi(providerForm.id, payload)
      : await createLLMProviderApi(payload);
    message.success('供应商已保存');
    providerModalVisible.value = false;
    await loadData();
  } catch (error) {
    if (error instanceof Error && error.message.includes('JSON')) {
      message.error(error.message);
    }
  } finally {
    saving.value = false;
  }
}

function confirmProviderDelete(provider: LLMProvider) {
  dialog.warning({
    title: '删除供应商',
    content: `确认删除“${provider.name}”及其下未选中的模型吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await deleteLLMProviderApi(provider.id);
      message.success('供应商已删除');
      await loadData();
    },
  });
}

function openModelCreate() {
  Object.assign(modelForm, {
    display_name: '',
    id: null,
    is_active: true,
    model_key: '',
    model_type: 'text',
    parametersText: '{}',
    provider:
      providers.value.find((provider) => provider.is_active)?.id ?? null,
  });
  modelModalVisible.value = true;
}

function openModelEdit(model: LLMModel) {
  Object.assign(modelForm, {
    display_name: model.display_name,
    id: model.id,
    is_active: model.is_active,
    model_key: model.model_key,
    model_type: model.model_type,
    parametersText: JSON.stringify(model.parameters, null, 2),
    provider: model.provider,
  });
  modelModalVisible.value = true;
}

async function saveModel() {
  await modelFormRef.value?.validate();
  if (!modelForm.provider) {
    return;
  }
  saving.value = true;
  try {
    const payload = {
      display_name: modelForm.display_name,
      is_active: modelForm.is_active,
      model_key: modelForm.model_key,
      model_type: modelForm.model_type,
      parameters: parseObject(modelForm.parametersText),
      provider: modelForm.provider,
    };
    modelForm.id
      ? await updateLLMModelApi(modelForm.id, payload)
      : await createLLMModelApi(payload);
    message.success('模型已保存');
    modelModalVisible.value = false;
    await loadData();
  } catch (error) {
    if (error instanceof Error && error.message.includes('JSON')) {
      message.error(error.message);
    }
  } finally {
    saving.value = false;
  }
}

function confirmModelDelete(model: LLMModel) {
  dialog.warning({
    title: '删除模型',
    content: `确认删除“${model.display_name}”吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await deleteLLMModelApi(model.id);
      message.success('模型已删除');
      await loadData();
    },
  });
}

async function saveSelection() {
  if (!selectedModelId.value) {
    message.error('请选择文本模型');
    return;
  }
  saving.value = true;
  try {
    await selectLLMModelApi('text', selectedModelId.value);
    message.success('当前文本模型已更新，将从下一轮对话开始生效');
    await loadData();
  } finally {
    saving.value = false;
  }
}

function clearSelection() {
  dialog.warning({
    title: '清除当前选择',
    content: '清除后文本对话将不可用，确认继续吗？',
    positiveText: '清除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await clearLLMSelectionApi('text');
      message.success('当前文本模型选择已清除');
      await loadData();
    },
  });
}

onMounted(loadData);
</script>
