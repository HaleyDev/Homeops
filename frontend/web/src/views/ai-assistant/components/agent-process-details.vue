<template>
  <section class="agent-process-details">
    <button
      :aria-controls="processId"
      :aria-expanded="expanded"
      class="process-toggle"
      type="button"
      @click="emit('update:expanded', !expanded)"
    >
      <IconifyIcon
        :icon="expanded ? 'lucide:chevron-down' : 'lucide:chevron-right'"
        aria-hidden="true"
        class="process-chevron"
      />
      <IconifyIcon aria-hidden="true" icon="lucide:brain" />
      <span class="process-title">思考与执行过程</span>
      <span class="process-summary" :data-incomplete="Boolean(message.streamError)">
        {{ summary }}
      </span>
    </button>

    <div
      v-if="expanded"
      :id="processId"
      ref="processBodyRef"
      class="process-body"
    >
      <section v-if="message.thinking" class="thinking-section">
        <div class="section-heading">
          <IconifyIcon aria-hidden="true" icon="lucide:brain" />
          <span>思考过程</span>
        </div>
        <div class="thinking-content">{{ message.thinking }}</div>
      </section>

      <section
        v-for="(toolCall, index) in message.toolCalls"
        :key="toolCall.id"
        :data-status="toolCall.status ?? 'unknown'"
        :data-tool-call-id="toolCall.id"
        class="tool-call-card"
        tabindex="-1"
      >
        <div class="tool-call-heading">
          <IconifyIcon
            :class="{ 'is-spinning': toolCall.status === 'running' }"
            :icon="toolStatusIcon(toolCall.status)"
            aria-hidden="true"
          />
          <span class="tool-call-index">工具调用 #{{ index + 1 }}</span>
          <span class="tool-name" :title="toolCall.name">
            {{ getToolMeta(toolCall.name).label }}
          </span>
          <span class="tool-status" :data-status="toolCall.status ?? 'unknown'">
            {{ toolStatusText(toolCall.status) }}
          </span>
        </div>
        <div v-if="getToolMeta(toolCall.name).label !== toolCall.name" class="tool-raw-name">
          {{ toolCall.name }}
        </div>
        <div class="tool-detail">
          <span class="detail-label">调用参数</span>
          <pre>{{ formatToolData(toolCall.args) }}</pre>
        </div>
        <div v-if="toolCall.result !== undefined" class="tool-detail">
          <span class="detail-label">返回结果</span>
          <pre>{{ formatToolData(toolCall.result) }}</pre>
        </div>
      </section>
    </div>
  </section>
</template>

<script lang="ts" setup>
import type { ChatToolCallStatus } from '#/api/ai';

import type { ChatMessage } from '../types';

import { computed, nextTick, ref } from 'vue';

import { IconifyIcon } from '@vben/icons';

import { formatToolData, getToolMeta } from '../message-utils';

const props = defineProps<{
  expanded: boolean;
  message: ChatMessage;
}>();

const emit = defineEmits<{
  'update:expanded': [expanded: boolean];
}>();

const processBodyRef = ref<HTMLElement | null>(null);
const processId = `assistant-process-${props.message.uiKey}`;

const summary = computed(() => {
  const calls = props.message.toolCalls;
  const errorCount = calls.filter((call) => call.status === 'error').length;
  if (errorCount > 0) return `${errorCount} 次工具调用异常`;
  if (props.message.streamError) return '过程未完整结束';

  if (props.message.streaming) {
    const running = calls.findLast((call) => call.status === 'running');
    if (running) return `正在调用 ${running.name}`;
    if (calls.length > 0) return '工具调用完成，正在整理结果…';
    if (props.message.thinking) return '正在思考…';
    return '准备中…';
  }

  return calls.length > 0
    ? `${calls.length} 次工具调用`
    : '可查看思考过程';
});

function toolStatusText(status?: ChatToolCallStatus): string {
  if (!status) return '历史调用记录';
  return {
    error: '调用失败',
    incomplete: '未完成',
    running: '调用中…',
    success: '调用完成',
  }[status];
}

function toolStatusIcon(status?: ChatToolCallStatus): string {
  if (!status) return 'lucide:history';
  return {
    error: 'lucide:circle-x',
    incomplete: 'lucide:circle-dashed',
    running: 'lucide:loader-circle',
    success: 'lucide:circle-check',
  }[status];
}

/** 供底部工具图标定位；用数据比较而不是拼接 CSS 选择器，兼容任意调用 id。 */
async function scrollToTool(callId: string): Promise<void> {
  await nextTick();
  const target = Array.from(
    processBodyRef.value?.querySelectorAll<HTMLElement>('[data-tool-call-id]') ??
      [],
  ).find((element) => element.dataset.toolCallId === callId);
  target?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target?.focus({ preventScroll: true });
}

defineExpose({ scrollToTool });
</script>

<style scoped>
.agent-process-details {
  min-width: 0;
  margin-bottom: 10px;
  overflow: hidden;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 9px;
}

.process-toggle {
  display: flex;
  gap: 7px;
  align-items: center;
  width: 100%;
  min-height: 38px;
  padding: 8px 10px;
  color: var(--el-text-color-regular);
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  transition: background-color 0.2s;
}

.process-toggle:hover {
  background: var(--el-fill-color);
}

.process-toggle:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}

.process-chevron {
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
}

.process-title {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
}

.process-summary {
  min-width: 0;
  margin-left: auto;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-summary[data-incomplete='true'] {
  color: var(--el-color-warning);
}

.process-body {
  display: flex;
  flex-direction: column;
  gap: 9px;
  max-height: 380px;
  padding: 10px;
  overflow: auto;
  overscroll-behavior: contain;
  border-top: 1px solid var(--el-border-color-lighter);
}

.thinking-section,
.tool-call-card {
  flex-shrink: 0;
  padding: 9px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 7px;
}

.tool-call-card:focus {
  border-color: var(--el-color-primary);
  outline: 2px solid var(--el-color-primary-light-7);
}

.section-heading,
.tool-call-heading {
  display: flex;
  gap: 6px;
  align-items: center;
  min-width: 0;
  font-size: 12px;
  font-weight: 600;
}

.thinking-content {
  max-height: 180px;
  margin-top: 7px;
  overflow: auto;
  color: var(--el-text-color-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.tool-call-index {
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  font-weight: 400;
}

.tool-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-raw-name {
  margin-top: 3px;
  color: var(--el-text-color-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
}

.tool-status {
  flex-shrink: 0;
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  font-weight: 400;
}

.tool-status[data-status='success'] {
  color: var(--el-color-success);
}

.tool-status[data-status='error'] {
  color: var(--el-color-danger);
}

.tool-status[data-status='incomplete'] {
  color: var(--el-color-warning);
}

.tool-detail {
  margin-top: 8px;
}

.detail-label {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.tool-detail pre {
  max-height: 200px;
  padding: 8px;
  margin: 4px 0 0;
  overflow: auto;
  color: var(--el-text-color-regular);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.is-spinning {
  animation: process-spin 1s linear infinite;
}

@keyframes process-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
