<script setup lang="ts">
import type {
  BubbleListProps,
} from 'vue-element-plus-x/types/BubbleList';
import type { ConversationItem } from 'vue-element-plus-x/types/Conversations';

import type { ChatConversation, ChatMessage } from './types';

import { onBeforeUnmount, ref } from 'vue';
import { BubbleList, Conversations, XSender } from 'vue-element-plus-x';

// Element Plus 基础变量表(:root 的 --el-* 定义)。
// vue-element-plus-x 只带组件样式不带变量表,缺了它:
// 气泡圆角/边框/底色等所有 var(--el-*) 全部失效(方形气泡、无边框)。
import 'element-plus/theme-chalk/el-var.css';
// Element Plus 暗色变量表:html.dark 下重定义 --el-* 变量,
// Bubble 等纯变量组件与 el-button/el-avatar 自动跟随暗色主题
import 'element-plus/theme-chalk/dark/css-vars.css';

import { message } from '#/adapter/naive';
import { sendChatStreamApi } from '#/api/ai';

import {
  AI_AVATAR,
  USER_AVATAR,
  createDefaultConversations,
  createWelcomeMessage,
} from './constants';
import { renderMarkdown } from './markdown';

defineOptions({ name: 'AiAssistant' });

// ==================== 左侧:会话列表(本地维护,待接会话接口) ====================

const conversations = ref<ChatConversation[]>(createDefaultConversations());
// Conversations 组件的 active 为 string | number,这里保持一致避免 v-model 类型冲突
const activeConversation = ref<string | number | undefined>(
  conversations.value[0]?.id,
);

/** 当前对话的后端会话 id,由 session 事件下发;新会话时清空 */
const sessionId = ref<string>();

/** 新建会话:本地追加并重置对话区 */
function handleNewConversation() {
  const item: ChatConversation = {
    id: `conv-new-${Date.now()}`,
    label: '新会话',
  };
  conversations.value.push(item);
  activeConversation.value = item.id;
  resetMessages();
}

/** 切换会话:重置对话区(会话历史接口就绪后改为拉取历史) */
function handleConversationChange(item: ConversationItem) {
  const id = String(item.id ?? '');
  if (!id || id === activeConversation.value) return;
  activeConversation.value = id;
  resetMessages();
}

// ==================== 右侧:聊天区(对接 POST /api/ai/chat/ SSE) ====================

type MessageList = BubbleListProps<ChatMessage>['list'];

const messages = ref<MessageList>([createWelcomeMessage()]);
const senderLoading = ref(false);
/** 流式过程中的状态提示(思考中 / 调用工具) */
const streamStatus = ref('');
const senderRef = ref<InstanceType<typeof XSender>>();

/** 进行中请求的中断控制器 */
let abortController: null | AbortController = null;

/** 读取输入框纯文本:getModelValue() 返回 { html, text } 对象,不是字符串 */
function readSenderText(): string {
  const model = senderRef.value?.getModelValue() as unknown;
  if (typeof model === 'string') return model;
  if (model && typeof model === 'object' && 'text' in model) {
    return String((model as { text?: string }).text ?? '');
  }
  return '';
}

function handleSubmit(value?: unknown) {
  const raw =
    typeof value === 'string' && value.trim() ? value : readSenderText();
  const question = raw.trim();
  if (!question || senderLoading.value) return;

  // 读取后主动清空输入框,不依赖组件内部的清空时机
  senderRef.value?.clear();

  messages.value.push({
    key: `msg-user-${Date.now()}`,
    role: 'user',
    placement: 'end',
    variant: 'outlined',
    shape: 'round',
    avatar: USER_AVATAR,
    content: question,
  });

  const replyKey = `msg-ai-${Date.now()}`;
  messages.value.push({
    key: replyKey,
    role: 'ai',
    placement: 'start',
    variant: 'filled',
    shape: 'round',
    avatar: AI_AVATAR,
    content: '',
    loading: true,
  });

  senderLoading.value = true;
  streamStatus.value = '';
  abortController?.abort();
  abortController = new AbortController();

  // 新会话收到首条消息后,用问题作为会话名
  const conversation = conversations.value.find(
    (item) => item.id === activeConversation.value,
  );
  if (conversation && conversation.label === '新会话') {
    conversation.label = question.slice(0, 20);
  }

  const appendReplyText = (text: string) => {
    const target = messages.value.find((item) => item.key === replyKey);
    if (target) {
      target.loading = false;
      target.content = String(target.content ?? '') + text;
    }
  };

  const finishReply = () => {
    const target = messages.value.find((item) => item.key === replyKey);
    if (target) target.loading = false;
    senderLoading.value = false;
    streamStatus.value = '';
  };

  sendChatStreamApi({
    message: question,
    sessionId: sessionId.value,
    signal: abortController.signal,
    onEvent: ({ data, event }) => {
      switch (event) {
        case 'session': {
          sessionId.value = data.session_id;
          break;
        }
        case 'text': {
          appendReplyText(data.detail ?? '');
          break;
        }
        case 'thinking': {
          streamStatus.value = '思考中…';
          break;
        }
        case 'tool_call': {
          streamStatus.value = `调用工具:${data.name ?? ''}`;
          break;
        }
        case 'tool_response': {
          streamStatus.value = '整理结果…';
          break;
        }
        case 'done': {
          finishReply();
          break;
        }
        case 'error': {
          message.error(`AI 服务出错:${data.message ?? '未知错误'}`);
          finishReply();
          break;
        }
      }
    },
  }).catch((error: unknown) => {
    // 主动中断不算错误
    if ((error as Error)?.name === 'AbortError') return;
    message.error((error as Error)?.message || 'AI 服务连接失败');
    finishReply();
  });
}

/** 中断当前流式输出 */
function handleCancel() {
  abortController?.abort();
  abortController = null;
  senderLoading.value = false;
  streamStatus.value = '';
  const streaming = messages.value.find((item) => item.loading);
  if (streaming) streaming.loading = false;
}

function resetMessages() {
  handleCancel();
  sessionId.value = undefined;
  messages.value = [createWelcomeMessage()];
}

onBeforeUnmount(() => {
  handleCancel();
});
</script>

<template>
  <!-- 高度按 Vben 布局(头部 + 标签栏 + 内边距)预留,可按实际主题微调 -->
  <div
    class="ai-assistant-page flex h-[calc(100vh-120px)] min-h-[480px] w-full gap-3"
  >
    <!-- 左侧:会话列表 -->
    <aside
      class="bg-card border-border flex w-56 shrink-0 flex-col gap-2 rounded-xl border p-2"
    >
      <button
        class="border-border text-foreground hover:bg-accent w-full rounded-md border px-2 py-1.5 text-sm transition select-none hover:cursor-pointer"
        type="button"
        @click="handleNewConversation"
      >
        + 新建会话
      </button>
      <div class="min-h-0 flex-1 overflow-auto">
        <!-- 组件把白底/280px 宽度/内边距以内联样式写在列表上,
             必须通过 style prop 覆盖(合并规则:传入值优先于内置默认值) -->
        <Conversations
          v-model:active="activeConversation"
          :items="conversations"
          :label-max-width="150"
          :style="{
            backgroundColor: 'transparent',
            height: 'auto',
            padding: '0',
            width: '100%',
          }"
          row-key="id"
          @change="handleConversationChange"
        />
      </div>
    </aside>

    <!-- 右侧:聊天区 -->
    <main
      class="bg-card border-border flex min-w-0 flex-1 flex-col gap-2 rounded-xl border p-3"
    >
      <div class="min-h-0 flex-1">
        <BubbleList :list="messages" class="h-full" max-height="100%">
          <!-- AI 气泡渲染 markdown;用户气泡保持纯文本 -->
          <template #content="{ item }">
            <div
              v-if="item.role === 'ai'"
              class="md-body"
              v-html="renderMarkdown(String(item.content ?? ''))"
            ></div>
            <span v-else class="whitespace-pre-wrap">{{ item.content }}</span>
          </template>
        </BubbleList>
      </div>
      <div v-if="streamStatus" class="text-muted-foreground px-1 text-xs">
        {{ streamStatus }}
      </div>
      <div class="shrink-0">
        <XSender
          ref="senderRef"
          :loading="senderLoading"
          clearable
          placeholder="请输入你的问题…"
          @cancel="handleCancel"
          @submit="handleSubmit"
        />
      </div>
    </main>
  </div>
</template>

<!--
  第三方组件(elx)主题适配,非 scoped:
  - Bubble 全部使用 --el-* 变量,EP 暗色变量引入后自动生效;
  - XSender 暴露 --chat-* 主题变量,这里统一映射到 Element Plus token(亮暗色都跟随应用);
  - Conversations 存在少量硬编码颜色,暗色下定向覆盖。
-->
<style>
/* 亮色下也对齐应用主题色(双类名提高优先级,覆盖库内 :root 默认值) */
.ai-assistant-page.ai-assistant-page {
  --chat-primary: var(--el-color-primary);
  --chat-highlight: var(--el-color-primary-light-3);
}

/* 发送按钮的加载动画:默认 SVG 占满按钮宽度,观感过大,收敛到 16px */
.ai-assistant-page .elx-x-sender__loading-svg {
  width: 16px !important;
  height: 16px !important;
}

/* 输入框容器:库默认 8px 圆角,加大到 12px 更柔和 */
.ai-assistant-page .elx-x-sender {
  border-radius: 12px;
}

/* ===== 暗色主题 ===== */
.dark .ai-assistant-page {
  --chat-text: var(--el-text-color-primary);
  --chat-text-assistant: var(--el-text-color-regular);
  --chat-text-secondary: var(--el-text-color-secondary);
  --chat-text-placeholder: var(--el-text-color-placeholder);
  --chat-box: var(--el-bg-color);
  --chat-box-shadow: none;
  --chat-input: var(--el-bg-color);
  --chat-input-border: var(--el-border-color);
  --chat-input-shadow-color: transparent;
  --chat-card: var(--el-fill-color-light);
  --chat-highlight-card: var(--el-fill-color);
  --chat-disabled: var(--el-fill-color);
  --chat-popover: var(--el-bg-color-overlay);
  --chat-popover-text: var(--el-text-color-primary);
}

.dark .ai-assistant-page .elx-conversations {
  color: var(--el-text-color-primary);
}

.dark .ai-assistant-page .elx-conversations-item__content .elx-conversations-item__label {
  color: var(--el-text-color-primary);
}

.dark
  .ai-assistant-page
  .elx-conversations-item__content
  .elx-conversations-item__timestamp {
  color: var(--el-text-color-secondary);
}

.dark .ai-assistant-page .elx-conversations-item:hover,
.dark .ai-assistant-page .elx-conversations-item--hovered,
.dark .ai-assistant-page .elx-conversations-item--menu-opened {
  background: var(--el-fill-color-light);
}

/* 列表根元素的浅色投影,暗色下去掉 */
.dark .ai-assistant-page .elx-conversations {
  box-shadow: none;
}

/* 选中态高亮:主色浅底(库内默认只有灰色,与 hover 无区分);
   --el-color-primary-light-9 在暗色变量表中自动变为深色调,两种主题通用 */
.ai-assistant-page .elx-conversations-item.elx-conversations-item--active {
  background: var(--el-color-primary-light-9);
}

/* 会话项自带 20px 右外边距(为库默认 280px 卡片宽设计),
   导致选中/悬停背景不满整行,撑满 */
.ai-assistant-page .elx-conversations .elx-conversations-item {
  margin-right: 0;
}

/* 关键:组件根元素自带 width: fit-content(收缩到内容宽度),
   会把整个列表缩成最长标题的宽度,条目高亮自然只占半行;
   双类名提高优先级,强制撑满侧栏 */
.ai-assistant-page .elx-conversations.elx-conversations {
  width: 100%;
}

.dark .ai-assistant-page .elx-conversations-item--disabled {
  color: var(--el-text-color-placeholder);
}

.dark
  .ai-assistant-page
  .elx-conversations__group
  .elx-conversations__group-title {
  color: var(--el-text-color-secondary);
}

/* ===== markdown 渲染样式(全部走 EP 变量,自动暗色) ===== */
.ai-assistant-page .md-body {
  line-height: 1.65;
  word-break: break-word;
}

.ai-assistant-page .md-body p {
  margin: 0 0 6px;
}

.ai-assistant-page .md-body > :last-child {
  margin-bottom: 0;
}

.ai-assistant-page .md-body h1,
.ai-assistant-page .md-body h2,
.ai-assistant-page .md-body h3,
.ai-assistant-page .md-body h4 {
  margin: 10px 0 6px;
  font-weight: 600;
  line-height: 1.4;
}

.ai-assistant-page .md-body h1 {
  font-size: 1.25em;
}

.ai-assistant-page .md-body h2 {
  font-size: 1.15em;
}

.ai-assistant-page .md-body h3 {
  font-size: 1.05em;
}

.ai-assistant-page .md-body ul,
.ai-assistant-page .md-body ol {
  margin: 4px 0;
  padding-left: 20px;
}

.ai-assistant-page .md-body li {
  margin: 2px 0;
}

.ai-assistant-page .md-body code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--el-fill-color);
  color: var(--el-color-danger);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
}

.ai-assistant-page .md-body pre {
  margin: 6px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  overflow-x: auto;
}

.ai-assistant-page .md-body pre code {
  padding: 0;
  background: transparent;
  color: var(--el-text-color-primary);
}

.ai-assistant-page .md-body blockquote {
  margin: 6px 0;
  padding: 2px 12px;
  border-left: 3px solid var(--el-border-color);
  color: var(--el-text-color-secondary);
}

.ai-assistant-page .md-body table {
  margin: 6px 0;
  border-collapse: collapse;
}

.ai-assistant-page .md-body th,
.ai-assistant-page .md-body td {
  padding: 4px 10px;
  border: 1px solid var(--el-border-color);
}

.ai-assistant-page .md-body a {
  color: var(--el-color-primary);
}

.ai-assistant-page .md-body hr {
  margin: 8px 0;
  border: none;
  border-top: 1px solid var(--el-border-color);
}

.ai-assistant-page .md-body img {
  max-width: 100%;
}
</style>
