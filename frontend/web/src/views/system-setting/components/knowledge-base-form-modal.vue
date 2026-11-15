<template>
  <NModal
    :show="show"
    preset="card"
    :title="knowledgeBase ? '编辑知识库' : '新建知识库'"
    style="width: min(560px, calc(100vw - 32px))"
    :closable="!saving"
    :mask-closable="!saving"
    @update:show="emit('update:show', $event)"
  >
    <NForm
      ref="formRef"
      :model="form"
      :rules="rules"
      label-placement="top"
    >
      <NFormItem label="知识库名称" path="name">
        <NInput
          v-model:value="form.name"
          maxlength="50"
          show-count
          placeholder="例如：运维制度"
          @keyup.enter="submit"
        />
      </NFormItem>
      <NFormItem label="内容说明" path="description">
        <NInput
          v-model:value="form.description"
          type="textarea"
          maxlength="300"
          show-count
          :autosize="{ minRows: 4, maxRows: 8 }"
          placeholder="说明该知识库包含的内容和用途"
        />
      </NFormItem>
    </NForm>
    <template #footer>
      <div class="flex justify-end gap-2">
        <NButton :disabled="saving" @click="emit('update:show', false)">
          取消
        </NButton>
        <NButton type="primary" :loading="saving" @click="submit">
          保存
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import type { FormInst, FormRules } from 'naive-ui';

import type {
  CreateKnowledgeBaseParams,
  KnowledgeBase,
} from '#/api/knowledge';

import { reactive, ref, watch } from 'vue';

import { NButton, NForm, NFormItem, NInput, NModal } from 'naive-ui';

const props = withDefaults(
  defineProps<{
    knowledgeBase?: KnowledgeBase | null;
    saving?: boolean;
    show: boolean;
  }>(),
  {
    knowledgeBase: null,
    saving: false,
  },
);

const emit = defineEmits<{
  submit: [value: CreateKnowledgeBaseParams];
  'update:show': [value: boolean];
}>();

const formRef = ref<FormInst | null>(null);
const form = reactive({ description: '', name: '' });

const rules: FormRules = {
  description: [
    {
      required: true,
      validator: (_rule, value) =>
        String(value ?? '').trim()
          ? true
          : new Error('请输入内容说明'),
      trigger: ['blur', 'input'],
    },
    { max: 300, message: '内容说明不能超过 300 个字符', trigger: 'blur' },
  ],
  name: [
    {
      required: true,
      validator: (_rule, value) =>
        String(value ?? '').trim() ? true : new Error('请输入知识库名称'),
      trigger: ['blur', 'input'],
    },
    { max: 50, message: '知识库名称不能超过 50 个字符', trigger: 'blur' },
  ],
};

watch(
  () => props.show,
  (show) => {
    if (!show) return;
    form.name = props.knowledgeBase?.name ?? '';
    form.description = props.knowledgeBase?.description ?? '';
    formRef.value?.restoreValidation();
  },
);

async function submit() {
  await formRef.value?.validate();
  emit('submit', {
    description: form.description.trim(),
    name: form.name.trim(),
  });
}
</script>
