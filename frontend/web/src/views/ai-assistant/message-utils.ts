import type {
  ChatApiMessage,
  ChatStreamEvent,
  ChatToolCallData,
  ChatToolCallStatus,
} from '#/api/ai';

import type { AssistantToolCall, ChatMessage } from './types';

import { AI_AVATAR, USER_AVATAR } from './constants';

const VALID_TOOL_STATUSES = new Set<ChatToolCallStatus>([
  'error',
  'incomplete',
  'running',
  'success',
]);

const TOOL_META: Record<string, { icon: string; label: string }> = {
  get_server_status: {
    icon: 'lucide:server',
    label: '服务器状态查询',
  },
};

export interface NormalizeChatMessageOptions {
  loading?: boolean;
  processExpanded?: boolean;
  streamError?: string;
  streaming?: boolean;
  uiKey: string;
}

export interface ToolUsageSummary {
  count: number;
  firstCallId: string;
  hasError: boolean;
  name: string;
  status: 'error' | 'incomplete' | 'running' | 'success' | 'unknown';
}

function hasOwn(value: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function normalizeStatus(
  status: ChatToolCallData['status'],
): ChatToolCallStatus | undefined {
  return status && VALID_TOOL_STATUSES.has(status) ? status : undefined;
}

function normalizeArgs(
  args: ChatToolCallData['args'],
): Record<string, unknown> {
  return args && typeof args === 'object' && !Array.isArray(args) ? args : {};
}

/**
 * 同时用于历史和流式事件。旧记录缺少 id 时生成稳定渲染 id，
 * 缺少 status 时保持 undefined，绝不把旧记录伪装成成功。
 */
export function normalizeToolCall(
  toolCall: ChatToolCallData,
  index: number,
  messageIdentity: number | string,
): AssistantToolCall {
  const normalized: AssistantToolCall = {
    args: normalizeArgs(toolCall.args),
    id:
      typeof toolCall.id === 'string' && toolCall.id.trim()
        ? toolCall.id
        : `legacy-${messageIdentity}-${index}`,
    name:
      typeof toolCall.name === 'string' && toolCall.name.trim()
        ? toolCall.name
        : 'unknown_tool',
  };
  const status = normalizeStatus(toolCall.status);
  if (status) normalized.status = status;
  // null 也是合法工具结果，只有字段不存在时才不展示结果区域。
  if (hasOwn(toolCall, 'result')) normalized.result = toolCall.result;
  return normalized;
}

/** 历史与实时消息的唯一归一化入口。 */
export function normalizeChatMessage(
  message: ChatApiMessage,
  options: NormalizeChatMessageOptions,
): ChatMessage {
  const isUser = message.role === 'user';
  const identity = message.id ?? options.uiKey;
  const normalized: ChatMessage = {
    avatar: isUser ? USER_AVATAR : AI_AVATAR,
    content: message.content ?? '',
    key: options.uiKey,
    loading: options.loading ?? false,
    placement: isUser ? 'end' : 'start',
    processExpanded: options.processExpanded ?? false,
    role: isUser ? 'user' : 'ai',
    shape: 'round',
    streaming: options.streaming ?? false,
    thinking: message.thinking ?? '',
    toolCalls: (message.tool_calls ?? []).map((toolCall, index) =>
      normalizeToolCall(toolCall, index, identity),
    ),
    uiKey: options.uiKey,
    variant: isUser ? 'outlined' : 'filled',
  };
  if (message.id !== undefined) normalized.id = message.id;
  if (message.created_at) normalized.createdAt = message.created_at;
  if (options.streamError) normalized.streamError = options.streamError;
  return normalized;
}

/** 合并 tool_call/tool_response；同一 id 永远只保留一条有序记录。 */
export function mergeToolCall(
  toolCalls: readonly AssistantToolCall[],
  incoming: ChatToolCallData,
  event: 'tool_call' | 'tool_response',
  messageIdentity: number | string,
): AssistantToolCall[] {
  const incomingId =
    typeof incoming.id === 'string' && incoming.id.trim()
      ? incoming.id
      : undefined;
  let matchIndex = incomingId
    ? toolCalls.findIndex((toolCall) => toolCall.id === incomingId)
    : -1;

  // 对兼容事件保留设计中的无 id 配对规则：从后向前找同名 running 调用。
  if (event === 'tool_response' && matchIndex < 0 && !incomingId) {
    for (let index = toolCalls.length - 1; index >= 0; index -= 1) {
      const candidate = toolCalls[index];
      if (
        candidate &&
        candidate.name === incoming.name &&
        candidate.status === 'running'
      ) {
        matchIndex = index;
        break;
      }
    }
  }

  if (matchIndex < 0) {
    const normalized = normalizeToolCall(
      incoming,
      toolCalls.length,
      messageIdentity,
    );
    if (event === 'tool_call' && !normalized.status) {
      normalized.status = 'running';
    }
    return [...toolCalls, normalized];
  }

  const existing = toolCalls[matchIndex]!;
  const status =
    normalizeStatus(incoming.status) ??
    existing.status ??
    (event === 'tool_call' ? 'running' : undefined);
  const merged = normalizeToolCall(
    {
      ...incoming,
      args: incoming.args ?? existing.args,
      id: existing.id,
      name: incoming.name ?? existing.name,
      status,
    },
    matchIndex,
    messageIdentity,
  );
  if (!hasOwn(incoming, 'result') && hasOwn(existing, 'result')) {
    merged.result = existing.result;
  }
  return toolCalls.map((toolCall, index) =>
    index === matchIndex ? merged : toolCall,
  );
}

/** 处理当前请求的正文/思考/工具增量，不修改整轮 streaming 状态。 */
export function applyAssistantStreamEvent(
  message: ChatMessage,
  streamEvent: ChatStreamEvent,
): void {
  const { data, event } = streamEvent;
  switch (event) {
    case 'text': {
      message.loading = false;
      message.content += data.detail ?? '';
      break;
    }
    case 'thinking': {
      message.loading = false;
      message.thinking += data.detail ?? '';
      break;
    }
    case 'tool_call':
    case 'tool_response': {
      message.loading = false;
      message.toolCalls = mergeToolCall(
        message.toolCalls,
        data,
        event,
        message.id ?? message.uiKey,
      );
      break;
    }
  }
}

/** done 的持久化结果只校准业务内容，保留气泡键和用户折叠选择。 */
export function applyFinalAssistantMessage(
  target: ChatMessage,
  finalMessage: ChatApiMessage,
): ChatMessage {
  const normalized = normalizeChatMessage(finalMessage, {
    loading: false,
    processExpanded: target.processExpanded,
    streaming: false,
    uiKey: target.uiKey,
  });
  Object.assign(target, normalized);
  delete target.streamError;
  return target;
}

/** 异常/EOF/取消只结束当前消息，仍保留已收到的部分内容。 */
export function finishIncompleteAssistantMessage(
  message: ChatMessage,
  error: string,
): void {
  message.loading = false;
  message.streaming = false;
  message.streamError = error;
  message.toolCalls = message.toolCalls.map((toolCall) =>
    toolCall.status === 'running'
      ? { ...toolCall, status: 'incomplete' }
      : toolCall,
  );
}

export function hasProcessData(message: ChatMessage): boolean {
  return Boolean(message.thinking) || message.toolCalls.length > 0;
}

/** 正式回复下方按名称去重的工具摘要，重复调用仍保留在 toolCalls 中。 */
export function summarizeToolUsage(
  toolCalls: readonly AssistantToolCall[],
): ToolUsageSummary[] {
  const summaries = new Map<string, ToolUsageSummary>();
  for (const toolCall of toolCalls) {
    const existing = summaries.get(toolCall.name);
    if (existing) {
      existing.count += 1;
      existing.hasError ||= toolCall.status === 'error';
    } else {
      summaries.set(toolCall.name, {
        count: 1,
        firstCallId: toolCall.id,
        hasError: toolCall.status === 'error',
        name: toolCall.name,
        status: 'unknown',
      });
    }
  }

  for (const summary of summaries.values()) {
    const calls = toolCalls.filter((toolCall) => toolCall.name === summary.name);
    if (summary.hasError) {
      summary.status = 'error';
    } else if (calls.some((toolCall) => toolCall.status === 'running')) {
      summary.status = 'running';
    } else if (calls.some((toolCall) => toolCall.status === 'incomplete')) {
      summary.status = 'incomplete';
    } else if (calls.every((toolCall) => toolCall.status === 'success')) {
      summary.status = 'success';
    } else {
      summary.status = 'unknown';
    }
  }
  return [...summaries.values()];
}

export function getToolMeta(name: string): { icon: string; label: string } {
  return TOOL_META[name] ?? { icon: 'lucide:wrench', label: name };
}

export function formatToolData(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}
