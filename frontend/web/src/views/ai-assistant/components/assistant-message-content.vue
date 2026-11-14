<template>
  <div class="assistant-message-content">
    <AgentProcessDetails
      v-if="hasProcess"
      ref="processDetailsRef"
      :expanded="message.processExpanded"
      :message="message"
      @update:expanded="emit('update:processExpanded', $event)"
    />

    <!-- 正式回复独立于过程折叠区，流式更新不受开合影响。 -->
    <div
      v-if="message.content"
      class="md-body markdown-content"
      v-html="renderMarkdown(message.content)"
    ></div>

    <div
      v-if="message.streamError"
      class="stream-error"
      role="alert"
    >
      <IconifyIcon
        aria-hidden="true"
        class="stream-error-icon"
        icon="lucide:circle-alert"
      />
      <div class="stream-error-content">
        <strong class="stream-error-title">回复未完成</strong>
        <span class="stream-error-detail">{{ message.streamError }}</span>
      </div>
    </div>

    <div v-if="usedTools.length" class="used-tools" aria-label="本回答使用的工具">
      <span class="used-tools-label">使用工具</span>
      <span
        v-for="tool in usedTools"
        :key="tool.name"
        class="used-tool-item"
        :data-status="tool.status"
      >
        <button
          :aria-label="toolTooltip(tool)"
          :data-tool-name="tool.name"
          class="used-tool-button"
          type="button"
          @click="locateTool(tool.firstCallId)"
        >
          <IconifyIcon :icon="getToolMeta(tool.name).icon" aria-hidden="true" />
          <span v-if="tool.count > 1" class="used-tool-count">×{{ tool.count }}</span>
          <span
            v-if="tool.hasError || tool.status === 'incomplete'"
            class="used-tool-status-dot"
            aria-hidden="true"
          ></span>
        </button>
        <span class="used-tool-tooltip" role="tooltip">{{ toolTooltip(tool) }}</span>
      </span>
    </div>
  </div>
</template>

<script lang="ts" setup>
import type { ChatMessage } from '../types';
import type { ToolUsageSummary } from '../message-utils';

import { computed, nextTick, ref } from 'vue';

import { IconifyIcon } from '@vben/icons';

import AgentProcessDetails from './agent-process-details.vue';

import { renderMarkdown } from '../markdown';
import {
  getToolMeta,
  hasProcessData,
  summarizeToolUsage,
} from '../message-utils';

const props = defineProps<{
  message: ChatMessage;
}>();

const emit = defineEmits<{
  'update:processExpanded': [expanded: boolean];
}>();

const processDetailsRef = ref<InstanceType<typeof AgentProcessDetails> | null>(
  null,
);
const hasProcess = computed(() => hasProcessData(props.message));
const usedTools = computed(() => summarizeToolUsage(props.message.toolCalls));

function toolStatusText(status: ToolUsageSummary['status']): string {
  return {
    error: '存在调用异常',
    incomplete: '过程未完成',
    running: '调用中',
    success: '调用完成',
    unknown: '历史调用记录',
  }[status];
}

function toolTooltip(tool: ToolUsageSummary): string {
  return `${getToolMeta(tool.name).label} · ${tool.count} 次调用 · ${toolStatusText(tool.status)}`;
}

async function locateTool(firstCallId: string): Promise<void> {
  emit('update:processExpanded', true);
  await nextTick();
  await processDetailsRef.value?.scrollToTool(firstCallId);
}
</script>

<style scoped>
.assistant-message-content {
  min-width: 0;
}

/* v-html 节点没有本组件的 scoped 属性，内部 Markdown 必须使用 :deep。 */
.markdown-content {
  color: var(--el-text-color-primary);
  line-height: 1.65;
  word-break: break-word;
}

.markdown-content :deep(p) {
  margin: 0 0 6px;
}

.markdown-content :deep(> :last-child) {
  margin-bottom: 0;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  margin: 10px 0 6px;
  font-weight: 600;
  line-height: 1.4;
}

.markdown-content :deep(h1) {
  font-size: 1.25em;
}

.markdown-content :deep(h2) {
  font-size: 1.15em;
}

.markdown-content :deep(h3) {
  font-size: 1.05em;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}

.markdown-content :deep(li) {
  margin: 2px 0;
}

.markdown-content :deep(code) {
  padding: 1px 5px;
  color: var(--el-color-danger);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
  background: var(--el-fill-color);
  border-radius: 4px;
}

.markdown-content :deep(pre) {
  padding: 10px 12px;
  margin: 6px 0;
  overflow-x: auto;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.markdown-content :deep(pre code) {
  padding: 0;
  color: var(--el-text-color-primary);
  background: transparent;
}

.markdown-content :deep(blockquote) {
  padding: 2px 12px;
  margin: 6px 0;
  color: var(--el-text-color-secondary);
  border-left: 3px solid var(--el-border-color);
}

.markdown-content :deep(table) {
  margin: 6px 0;
  border-collapse: collapse;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: 4px 10px;
  border: 1px solid var(--el-border-color);
}

.markdown-content :deep(a) {
  color: var(--el-color-primary);
}

.markdown-content :deep(hr) {
  margin: 8px 0;
  border: none;
  border-top: 1px solid var(--el-border-color);
}

.markdown-content :deep(img) {
  max-width: 100%;
}

.stream-error {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px 12px;
  margin-top: 10px;
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border: 1px solid var(--el-color-danger-light-7);
  border-radius: 8px;
}

.assistant-message-content > .stream-error:first-child {
  margin-top: 0;
}

.stream-error-icon {
  flex-shrink: 0;
  margin-top: 2px;
  font-size: 16px;
}

.stream-error-content {
  min-width: 0;
}

.stream-error-title {
  display: block;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}

.stream-error-detail {
  display: block;
  margin-top: 2px;
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.used-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: center;
  margin-top: 10px;
  color: var(--el-text-color-secondary);
}

.used-tools-label {
  margin-right: 2px;
  font-size: 12px;
}

.used-tool-item {
  position: relative;
  display: inline-flex;
}

.used-tool-button {
  position: relative;
  display: inline-flex;
  gap: 2px;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 28px;
  padding: 0 6px;
  color: var(--el-color-primary);
  cursor: pointer;
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 7px;
  transition: background-color 0.2s;
}

.used-tool-button:hover,
.used-tool-button:focus-visible {
  background: var(--el-color-primary-light-8);
}

.used-tool-button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.used-tool-count {
  font-size: 10px;
  font-weight: 600;
}

.used-tool-status-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 7px;
  height: 7px;
  background: var(--el-color-danger);
  border: 1px solid var(--el-bg-color);
  border-radius: 50%;
}

.used-tool-item[data-status='incomplete'] .used-tool-status-dot {
  background: var(--el-color-warning);
}

.used-tool-tooltip {
  position: absolute;
  bottom: calc(100% + 7px);
  left: 50%;
  z-index: 10;
  width: max-content;
  max-width: 260px;
  padding: 5px 8px;
  color: var(--el-text-color-primary);
  font-size: 11px;
  line-height: 1.4;
  pointer-events: none;
  visibility: hidden;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  border-radius: 5px;
  box-shadow: var(--el-box-shadow-light);
  opacity: 0;
  transform: translate(-50%, 3px);
  transition: opacity 0.15s;
}

.used-tool-item:hover .used-tool-tooltip,
.used-tool-item:focus-within .used-tool-tooltip {
  visibility: visible;
  opacity: 1;
  transform: translate(-50%, 0);
}
</style>
