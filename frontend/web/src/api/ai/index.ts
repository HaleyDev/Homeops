/**
 * AI 助手接口(对接后端 backend/ai_assistant)
 *
 * POST /api/ai/chat/ —— SSE 流式对话
 * - 认证:SimpleJWT,与 requestClient 相同的 Bearer Token
 * - 事件帧格式:`event: <name>\ndata: <json>\n\n`
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

/** 后端 SSE 事件名。 */
export type ChatStreamEventName =
  | 'done'
  | 'error'
  | 'session'
  | 'text'
  | 'thinking'
  | 'tool_call'
  | 'tool_response';

export type ChatToolCallStatus = 'error' | 'incomplete' | 'running' | 'success';

/** 后端工具记录。旧历史数据可能只有 name/args，因此其它字段均可缺省。 */
export interface ChatToolCallData {
  args?: Record<string, unknown>;
  id?: string;
  name?: string;
  result?: unknown;
  status?: ChatToolCallStatus;
}

/** 历史消息及 done.assistant_message 共用的后端消息结构。 */
export interface ChatApiMessage {
  content?: null | string;
  created_at?: string;
  id?: number | string;
  role: 'assistant' | 'user';
  thinking?: null | string;
  tool_calls?: ChatToolCallData[] | null;
}

/** SSE 事件负载数据(各事件只用到其中部分字段)。 */
export interface ChatStreamEventData extends ChatToolCallData {
  assistant_message?: ChatApiMessage;
  detail?: string;
  message?: string;
  session_id?: string;
  total_tokens?: null | number;
}

/** 解析后的一条 SSE 事件。 */
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

/**
 * 发起流式对话。只有收到包含最终助手消息的 done 事件后才 resolve；
 * 解析、UI 回调、网络异常及无 done 的 EOF 均会 reject。
 */
export async function sendChatStreamApi(
  options: SendChatStreamOptions,
): Promise<ChatApiMessage> {
  const token = useAccessStore().accessToken;
  const response = await fetch(`${apiURL}/ai/chat/`, {
    body: JSON.stringify({
      message: options.message,
      ...(options.sessionId ? { session_id: options.sessionId } : {}),
    }),
    headers: {
      // DRF ChatView 只用 JSONRenderer 做内容协商；SSE 由 StreamingHttpResponse
      // 直接返回，不能只声明 text/event-stream，否则会在进入对话前返回 406。
      Accept: '*/*',
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
    throw new Error(`AI request failed (HTTP ${response.status}).`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let assistantMessage: ChatApiMessage | undefined;

  const dispatch = (frame: string) => {
    let eventName = 'message';
    const dataLines: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue;
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trimStart();
      } else if (line.startsWith('data:')) {
        // SSE 规范要求用换行连接多行 data，而不是直接拼接。
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length === 0) return;

    let data: ChatStreamEventData;
    try {
      data = JSON.parse(dataLines.join('\n')) as ChatStreamEventData;
    } catch (error) {
      console.error('[AI] Failed to parse SSE frame:', frame, error);
      throw new Error(
        'Failed to parse the AI streaming response. Please try again.',
        { cause: error },
      );
    }

    if (eventName === 'error') {
      throw new Error(
        data.message || 'Model invocation failed. Please try again later.',
      );
    }

    // 回调异常不能吞掉，否则上游仍会继续生成，页面也无法正确结束 loading。
    options.onEvent({
      data,
      event: eventName as ChatStreamEventName,
    });
    if (eventName === 'done') {
      if (!data.assistant_message) {
        throw new Error(
          'The AI completion event did not include the final assistant message. Please try again.',
        );
      }
      assistantMessage = data.assistant_message;
    }
  };

  try {
    let eof = false;
    while (!eof) {
      const { done, value } = await reader.read();
      eof = done;
      // done 时以 stream:false 刷新多字节字符的残留字节。
      buffer += decoder.decode(value, { stream: !done });

      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        dispatch(frame);
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
    }

    // 某些服务不会在最后一帧后写空行，EOF 前仍需派发残留帧。
    if (buffer.trim()) dispatch(buffer);
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }

  if (!assistantMessage) {
    throw new Error(
      'The stream ended without a completion event. Please try again.',
    );
  }
  return assistantMessage;
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
    messages: ChatApiMessage[];
  }>(`/ai/sessions/${sessionId}/messages/`);
}
