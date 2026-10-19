<script setup lang="ts">
import type {
  BubbleListProps,
} from 'vue-element-plus-x/types/BubbleList';
import type {
  ConversationItem,
  ConversationMenu,
  ConversationMenuCommand,
} from 'vue-element-plus-x/types/Conversations';

import type { ChatConversation, ChatMessage } from './types';

import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { BubbleList, Conversations, XSender } from 'vue-element-plus-x';

// Element Plus 基础变量表(:root 的 --el-* 定义)。
// vue-element-plus-x 只带组件样式不带变量表,缺了它:
// 气泡圆角/边框/底色等所有 var(--el-*) 全部失效(方形气泡、无边框)。
import 'element-plus/theme-chalk/el-var.css';
// Element Plus 暗色变量表:html.dark 下重定义 --el-* 变量,
// Bubble 等纯变量组件与 el-button/el-avatar 自动跟随暗色主题
import 'element-plus/theme-chalk/dark/css-vars.css';

import { dialog, message } from '#/adapter/naive';
import {
  createSessionApi,
  deleteSessionApi,
  getSessionMessagesApi,
  listSessionsApi,
  sendChatStreamApi,
} from '#/api/ai';

import { AI_AVATAR, USER_AVATAR, createWelcomeMessage } from './constants';
import { renderMarkdown } from './markdown';

defineOptions({ name: 'AiAssistant' });

// ==================== 左侧:会话列表(对接后端会话接口) ====================

const conversations = ref<ChatConversation[]>([]);
// Conversations 组件的 active 为 string | number,这里保持一致避免 v-model 类型冲突
const activeConversation = ref<string | number | undefined>(undefined);

/** Conversations 组件要 {id, label} 形状,由业务数据映射而来 */
const conversationItems = computed(() =>
  conversations.value.map((c) => ({ id: c.session_id, label: c.title })),
);

/** 当前对话的后端会话 id;新建/切换会话时持有,由 session 事件兜底 */
const sessionId = ref<string>();

/** 新建会话:后端建好空会话,推进列表并持有 session_id(不打断其它会话的流) */
async function handleNewConversation() {
  try {
    const res = await createSessionApi();
    // 先缓存当前会话的消息, 再切到新会话的空列表
    if (sessionId.value) {
      messagesBySession.set(sessionId.value, messages.value);
    }
    conversations.value.push({ session_id: res.session_id, title: res.title });
    activeConversation.value = res.session_id;
    sessionId.value = res.session_id;
    messagesBySession.set(res.session_id, [createWelcomeMessage()]);
    messages.value = [createWelcomeMessage()];
  } catch (error) {
    console.error('[AI] Failed to create session:', error);
    message.error('创建会话失败');
  }
}

/** 切换会话:缓存当前消息,展示目标会话(无缓存则从后端拉历史);不中断任何进行中的流 */
function handleConversationChange(item: ConversationItem) {
  const id = String(item.id ?? '');
  if (!id || id === activeConversation.value) return;
  if (sessionId.value) {
    messagesBySession.set(sessionId.value, messages.value);
  }
  activeConversation.value = id;
  sessionId.value = id;
  void showSessionMessages(id);
}

/** 侧边栏会话悬浮菜单: 只提供删除(重命名后续接 PATCH) */
const conversationMenu: ConversationMenu[] = [
  { label: '删除会话', key: 'delete', command: 'delete' },
];

/** 菜单命令入口: 目前只处理删除 */
async function handleConversationMenu(
  command: ConversationMenuCommand,
  item: ConversationItem,
) {
  if (command !== 'delete') return;
  await handleDeleteConversation(String(item.id ?? ''));
}

/** 删除会话: 确认 → 调后端 → 从列表移除; 删的是当前会话则切到第一个或复位 */
function handleDeleteConversation(targetId: string) {
  dialog.warning({
    title: '删除会话',
    content: '确定删除该会话及其全部消息吗？此操作不可恢复。',
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await deleteSessionApi(targetId);
        conversations.value = conversations.value.filter(
          (c) => c.session_id !== targetId,
        );
        if (activeConversation.value === targetId) {
          // 被删会话若在流式, 一并中止
          abortControllers.get(targetId)?.abort();
          abortControllers.delete(targetId);
          if (streamingSessionId.value === targetId) {
            streamingSessionId.value = null;
          }
          const next = conversations.value[0];
          if (next) {
            activeConversation.value = next.session_id;
            sessionId.value = next.session_id;
            void showSessionMessages(next.session_id);
          } else {
            activeConversation.value = undefined;
            sessionId.value = undefined;
            messages.value = [createWelcomeMessage()];
          }
        }
        message.success('会话已删除');
      } catch (error) {
        console.error('[AI] Failed to delete session:', error);
        message.error('删除会话失败');
      }
    },
  });
}

/** 页面加载:拉取当前用户的会话列表,默认选中第一个 */
onMounted(async () => {
  try {
    const list = await listSessionsApi();
    conversations.value = list.map((s) => ({
      session_id: s.session_id,
      title: s.title,
    }));
    if (list[0]) {
      activeConversation.value = list[0].session_id;
      sessionId.value = list[0].session_id;
      void showSessionMessages(list[0].session_id);
    }
  } catch (error) {
    console.error('[AI] Failed to load session list:', error);
    message.error('会话列表加载失败');
  }
});

// ==================== 右侧:聊天区(对接 POST /api/ai/chat/ SSE) ====================

type MessageList = BubbleListProps<ChatMessage>['list'];

/** 每个会话的消息缓存: 切换会话不销毁, 后台流继续写入对应数组 */
const messagesBySession = new Map<string, MessageList>();

/** 当前展示的会话消息 */
const messages = ref<MessageList>([createWelcomeMessage()]);

/** 当前正在流式输出的会话 id(null = 无) */
const streamingSessionId = ref<string | null>(null);

/** 当前视图是否处于流式: 发送按钮的 loading 态 */
const senderLoading = computed(
  () =>
    streamingSessionId.value !== null &&
    streamingSessionId.value === sessionId.value,
);

/** 流式过程中的状态提示(思考中 / 调用工具) */
const streamStatus = ref('');
const senderRef = ref<InstanceType<typeof XSender>>();

/** 每个会话各自的 AbortController: 取消只影响对应会话, 切换会话不中断 */
const abortControllers = new Map<string, AbortController>();

/** 后端消息 → 气泡列表(按顺序重建) */
function toBubbleList(
  messages: Array<{
    role: 'user' | 'assistant';
    content: string;
    thinking: string;
    tool_calls: Array<{ name: string; args: Record<string, unknown> }>;
    created_at: string;
  }>,
): MessageList {
  return messages.map((m, i) => ({
    key: `hist-${i}`,
    role: m.role === 'user' ? 'user' : 'ai',
    placement: m.role === 'user' ? 'end' : 'start',
    variant: m.role === 'user' ? 'outlined' : 'filled',
    shape: 'round',
    avatar: m.role === 'user' ? USER_AVATAR : AI_AVATAR,
    content: m.content,
  }));
}

/** 展示指定会话: 有缓存直接用; 无缓存先欢迎页, 同时从后端拉历史(已拉过的不再重复请求) */
async function showSessionMessages(id: string) {
  const cached = messagesBySession.get(id);
  if (cached) {
    messages.value = cached;
    return;
  }
  messages.value = [createWelcomeMessage()];
  try {
    const data = await getSessionMessagesApi(id);
    if (data.messages.length > 0) {
      const list = toBubbleList(data.messages);
      messagesBySession.set(id, list);
      // 仅当用户仍停留在此会话时才替换展示(防快速切换串台)
      if (activeConversation.value === id) {
        messages.value = list;
      }
    } else {
      // 空会话: 保留欢迎页, 但标记已缓存, 避免每次切换都请求
      messagesBySession.set(id, [createWelcomeMessage()]);
    }
  } catch (error) {
    console.error('[AI] Failed to load session history:', error);
    message.error('会话历史加载失败');
  }
}

/** 读取输入框纯文本:getModelValue() 返回 { html, text } 对象,不是字符串 */
function readSenderText(): string {
  const model = senderRef.value?.getModelValue() as unknown;
  if (typeof model === 'string') return model;
  if (model && typeof model === 'object' && 'text' in model) {
    return String((model as { text?: string }).text ?? '');
  }
  return '';
}

async function handleSubmit(value?: unknown) {
  const raw =
    typeof value === 'string' && value.trim() ? value : readSenderText();
  const question = raw.trim();
  if (!question || senderLoading.value) return;

  // 显式创建契约: 没有 session_id 就自动先建一个空会话
  let curSession = sessionId.value;
  if (!curSession) {
    try {
      const res = await createSessionApi();
      curSession = res.session_id;
      sessionId.value = curSession;
      conversations.value.push({ session_id: curSession, title: res.title });
      activeConversation.value = curSession;
      // 把当前(欢迎页)消息列表注册为该新会话的缓存
      messagesBySession.set(curSession, messages.value);
    } catch (error) {
      console.error('[AI] Failed to auto-create session:', error);
      message.error('创建会话失败');
      return;
    }
  }
  // 读取后主动清空输入框,不依赖组件内部的清空时机
  senderRef.value?.clear();

  // 追加到"当前会话的消息列表"引用上: 切换会话不会替换这个数组,
  // 后台流继续往里写, 切回来时直接看到累积的回复
  const replyList = messages.value;
  replyList.push({
    key: `msg-user-${Date.now()}`,
    role: 'user',
    placement: 'end',
    variant: 'outlined',
    shape: 'round',
    avatar: USER_AVATAR,
    content: question,
  });

  const replyKey = `msg-ai-${Date.now()}`;
  replyList.push({
    key: replyKey,
    role: 'ai',
    placement: 'start',
    variant: 'filled',
    shape: 'round',
    avatar: AI_AVATAR,
    content: '',
    loading: true,
  });

  streamStatus.value = '';
  // 每个会话独立控制器: 取消只影响本会话, 切换会话不中断
  abortControllers.get(curSession)?.abort();
  const controller = new AbortController();
  abortControllers.set(curSession, controller);
  streamingSessionId.value = curSession;

  // 新会话收到首条消息后,本地先把会话名更新为问题(后端同步更新标题)
  const conversation = conversations.value.find(
    (item) => item.session_id === activeConversation.value,
  );
  if (conversation && conversation.title === 'New Chat') {
    conversation.title = question.slice(0, 20);
  }

  const appendReplyText = (text: string) => {
    const target = replyList.find((item) => item.key === replyKey);
    if (target) {
      target.loading = false;
      target.content = String(target.content ?? '') + text;
    }
  };

  const finishReply = () => {
    const target = replyList.find((item) => item.key === replyKey);
    if (target) target.loading = false;
    if (streamingSessionId.value === curSession) {
      streamingSessionId.value = null;
      abortControllers.delete(curSession);
    }
    streamStatus.value = '';
  };

  sendChatStreamApi({
    message: question,
    sessionId: curSession,
    signal: controller.signal,
    onEvent: ({ data, event }) => {
      switch (event) {
        case 'session': {
          // 显式会话: 后端回显同一个 id; 仅当仍停留在本会话时才同步(防后台流污染当前视图)
          if (data.session_id && sessionId.value === curSession) {
            sessionId.value = data.session_id;
          }
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
          console.error(
            '[AI] Server sent error frame:',
            data.message ?? '(no message)',
          );
          message.error(`AI 服务出错:${data.message ?? '未知错误'}`);
          finishReply();
          break;
        }
      }
    },
  }).catch((error: unknown) => {
    // 主动中断/被替换都先清理本会话的 loading 态
    finishReply();
    if ((error as Error)?.name === 'AbortError') return;
    console.error('[AI] Chat stream error:', error);
    message.error((error as Error)?.message || 'AI 服务连接失败');
  });
}

/** 取消当前会话的流式输出(发送框的取消按钮) */
function handleCancel() {
  const cur = sessionId.value;
  if (cur) {
    abortControllers.get(cur)?.abort();
    abortControllers.delete(cur);
    if (streamingSessionId.value === cur) {
      streamingSessionId.value = null;
    }
  }
  streamStatus.value = '';
  for (const item of messages.value) {
    if (item.loading) item.loading = false;
  }
}

onBeforeUnmount(() => {
  // 离开页面: 中止所有会话的进行中请求
  abortControllers.forEach((c) => c.abort());
  abortControllers.clear();
  streamingSessionId.value = null;
});
</script>

<template>
  <!-- 高度按 Vben 布局(头部 + 标签栏 + 内边距)预留,可按实际主题微调;
       bg-muted/50:浅色下给白卡片垫出灰色底衬,否则白上叠白全靠细边框区分 -->
  <div
    class="bg-muted/50 ai-assistant-page flex h-[calc(100vh-120px)] min-h-[480px] w-full gap-3 rounded-xl p-2"
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
          :items="conversationItems"
          :label-max-width="150"
          :menu="conversationMenu"
          :style="{
            backgroundColor: 'transparent',
            height: 'auto',
            padding: '0',
            width: '100%',
          }"
          row-key="id"
          show-built-in-menu
          show-built-in-menu-type="hover"
          @change="handleConversationChange"
          @menu-command="handleConversationMenu"
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
      <div
        v-if="streamStatus && streamingSessionId === sessionId"
        class="text-muted-foreground px-1 text-xs"
      >
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

/* 输入框容器:库默认 8px 圆角、border-width 0(白底白框看不见),加大圆角并补边框 */
.ai-assistant-page .elx-x-sender {
  border-radius: 12px;
  border-width: 1px;
  border-color: var(--el-border-color);
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
