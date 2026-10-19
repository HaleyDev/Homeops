/**
 * AI 助手接口(对接后端 backend/ai_assistant)
 *
 * POST /api/ai/chat/ —— SSE 流式对话
 * - 认证:SimpleJWT,与 requestClient 相同的 Bearer Token
 * - 事件帧格式:`event: <name>\ndata: <json>\n\n`(见 backend/ai_assistant/services.py)
 *
 * 说明:浏览器端 axios 无法做流式读取,这里用 fetch + ReadableStream 解析 SSE;
 * token 过期(401)时不做自动刷新,提示用户重新登录后重试。
 */
import { useAppConfig } from '@vben/hooks';
import { useAccessStore } from '@vben/stores';
import { RequestClient } from '@vben/request';

const { apiURL } = useAppConfig(import.meta.env, import.meta.env.PROD);

const aiRequestClient = new RequestClient({ baseURL: apiURL });

aiRequestClient.addRequestInterceptor({
  fulfilled: async (config) => {
    const accessStore = useAccessStore();
    config.headers.Authorization = accessStore.accessToken
      ? `Bearer ${accessStore.accessToken}`
      : null;
    return config;
  },
});

// DRF 响应体即数据本体, 直接透传
aiRequestClient.addResponseInterceptor({
  fulfilled: (response) => response.data,
});

// 请求失败统一打日志, 方便控制台排查
aiRequestClient.addResponseInterceptor({
  rejected: (error) => {
    console.error('[AI] Request failed:', {
      method: error?.config?.method,
      url: error?.config?.url,
      status: error?.response?.status,
      responseData: error?.response?.data ?? error,
    });
    throw error;
  },
});

/** 后端 SSE 事件名(与 services.py 的 _frames 一一对应) */
export type ChatStreamEventName =
  | 'done'
  | 'error'
  | 'session'
  | 'text'
  | 'thinking'
  | 'tool_call'
  | 'tool_response';

/** SSE 事件负载数据(各事件只用到其中部分字段) */
export interface ChatStreamEventData {
  args?: Record<string, unknown>;
  detail?: string;
  message?: string;
  name?: string;
  session_id?: string;
  total_tokens?: null | number;
}

/** 解析后的一条 SSE 事件 */
export interface ChatStreamEvent {
  data: ChatStreamEventData;
  event: ChatStreamEventName;
}

export interface SendChatStreamOptions {
  /** 用户输入 */
  message: string;
  /** 会话 id: 后端要求先显式创建会话;页面层保证发送前 session_id 已存在(无则先自动创建) */
  sessionId?: string;
  /** 中断用 */
  signal?: AbortSignal;
  /** 每收到一帧回调一次 */
  onEvent: (event: ChatStreamEvent) => void;
}

/** 发起流式对话,连接关闭/流结束时 resolve;网络异常或非 2xx 时 reject */
export async function sendChatStreamApi(
  options: SendChatStreamOptions,
): Promise<void> {
  const token = useAccessStore().accessToken;
  const response = await fetch(`${apiURL}/ai/chat/`, {
    body: JSON.stringify({
      message: options.message,
      ...(options.sessionId ? { session_id: options.sessionId } : {}),
    }),
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
      'Content-Type': 'application/json',
    },
    method: 'POST',
    signal: options.signal,
  });

  if (!response.ok || !response.body) {
    const bodyText = await response.text().catch(() => '');
    console.error('[AI] Chat request HTTP error:', {
      status: response.status,
      statusText: response.statusText,
      body: bodyText,
    });
    throw new Error(`AI 接口请求失败(HTTP ${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (frame: string) => {
    let eventName = 'message';
    let rawData = '';
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        rawData += line.slice(5).trimStart();
      }
    }
    if (!rawData) return;
    try {
      options.onEvent({
        data: JSON.parse(rawData) as ChatStreamEventData,
        event: eventName as ChatStreamEventName,
      });
    } catch {
      // 单帧解析失败只跳过该帧,不影响整体流
      console.warn('[AI] Failed to parse SSE frame:', frame);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let separator = buffer.indexOf('\n\n');
    while (separator >= 0) {
      dispatch(buffer.slice(0, separator));
      buffer = buffer.slice(separator + 2);
      separator = buffer.indexOf('\n\n');
    }
  }
}

// ==================== 会话管理(业务表, 走 requestClient) ====================

/** 会话(业务表)结构,与后端 ChatSession 序列化对应 */
export interface ChatSessionItem {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

/** 新建会话: 点 ➕ 时调用, 后端返回带 session_id 的空会话 */
export async function createSessionApi(title?: string) {
  return aiRequestClient.post<ChatSessionItem>('/ai/sessions/', { title });
}

/** 当前用户的会话列表: 页面加载时填充侧边栏 */
export async function listSessionsApi() {
  return aiRequestClient.get<ChatSessionItem[]>('/ai/sessions/');
}

/** 删除会话 */
export async function deleteSessionApi(sessionId: string) {
  return aiRequestClient.delete(`/ai/sessions/${sessionId}/`);
}

/** 单会话全部消息: 切换会话窗口时回放 */
export async function getSessionMessagesApi(sessionId: string) {
  return aiRequestClient.get<{
    session_id: string;
    title: string;
    messages: Array<{
      role: 'user' | 'assistant';
      content: string;
      thinking: string;
      tool_calls: Array<{ name: string; args: Record<string, unknown> }>;
      created_at: string;
    }>;
  }>(`/ai/sessions/${sessionId}/messages/`);
}
