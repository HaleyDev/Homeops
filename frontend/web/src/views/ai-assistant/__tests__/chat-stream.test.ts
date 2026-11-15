import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatApiMessage, ChatStreamEvent } from '../../../api/ai';

import { sendChatStreamApi } from '../../../api/ai';

vi.mock('@vben/hooks', () => ({
  useAppConfig: () => ({ apiURL: '/api' }),
}));

vi.mock('@vben/stores', () => ({
  useAccessStore: () => ({ accessToken: 'test-token' }),
}));

vi.mock('@vben/request', () => ({
  RequestClient: class {
    addRequestInterceptor() {}
    addResponseInterceptor() {}
  },
}));

const encoder = new TextEncoder();
const fetchMock = vi.fn();

function createStreamResponse(
  chunks: Uint8Array[],
  onCancel: () => void = () => {},
): Response {
  let index = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      const chunk = chunks[index];
      if (chunk) {
        controller.enqueue(chunk);
        index += 1;
      } else {
        controller.close();
      }
    },
    cancel: onCancel,
  });
  return new Response(stream, {
    headers: { 'Content-Type': 'text/event-stream' },
    status: 200,
  });
}

function mockStreamResponse(
  chunks: Array<string | Uint8Array>,
  onCancel?: () => void,
) {
  const response = createStreamResponse(
    chunks.map((chunk) =>
      typeof chunk === 'string' ? encoder.encode(chunk) : chunk,
    ),
    onCancel,
  );
  fetchMock.mockResolvedValue(response);
  return response;
}

const finalMessage: ChatApiMessage = {
  id: 7,
  role: 'assistant',
  content: '最终正文',
  thinking: '最终思考',
  tool_calls: [],
  created_at: '2026-11-14T12:00:00Z',
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('sendChatStreamApi', () => {
  it('支持 LF/CRLF、多行 data、多字节分片和无末尾空行的 done', async () => {
    const textFrame = encoder.encode(
      'event: text\ndata: {"detail":"你好👋"}\n\n',
    );
    // 最后一个字符的 UTF-8 字节被拆到两个 chunk，验证 decoder 的流式解码。
    const splitAt = textFrame.length - 8 + 1;
    const response = mockStreamResponse([
      'event: session\r\ndata: {"session_id":"s1"}\r\n\r\n',
      'event: thinking\ndata: {"detail":\ndata: "思考"}\n\n',
      textFrame.slice(0, splitAt),
      textFrame.slice(splitAt),
      `event: done\ndata: ${JSON.stringify({
        total_tokens: 3,
        assistant_message: finalMessage,
      })}`,
    ]);
    const events: ChatStreamEvent[] = [];

    const result = await sendChatStreamApi({
      message: '状态如何',
      sessionId: 's1',
      onEvent: (event) => events.push(event),
    });

    expect(result).toEqual(finalMessage);
    expect(events.map((event) => event.event)).toEqual([
      'session',
      'thinking',
      'text',
      'done',
    ]);
    expect(events[1]?.data.detail).toBe('思考');
    expect(events[2]?.data.detail).toBe('你好👋');
    expect(response.body?.locked).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ai/chat/',
      expect.objectContaining({
        headers: expect.objectContaining({
          // 回归：不能让 DRF JSONRenderer 因仅接受 SSE 而拒绝请求。
          Accept: '*/*',
          Authorization: 'Bearer test-token',
        }),
      }),
    );
  });

  it('eof 没有 done 时 reject，避免页面永久 loading', async () => {
    mockStreamResponse(['event: text\ndata: {"detail":"部分正文"}\n\n']);

    await expect(
      sendChatStreamApi({ message: 'test', onEvent: () => {} }),
    ).rejects.toThrow('without a completion event');
  });

  it('解析异常会 cancel reader 并 releaseLock', async () => {
    const cancel = vi.fn();
    const response = mockStreamResponse(
      [
        'event: text\ndata: {bad json}\n\n',
        'event: text\ndata: {"detail":"later"}',
      ],
      cancel,
    );
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});

    await expect(
      sendChatStreamApi({ message: 'test', onEvent: () => {} }),
    ).rejects.toThrow('Failed to parse the AI streaming response');
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(response.body?.locked).toBe(false);
    expect(error).toHaveBeenCalled();
  });

  it('ui 回调异常不会被吞掉，并会取消上游读取', async () => {
    const cancel = vi.fn();
    const response = mockStreamResponse(
      [
        'event: text\ndata: {"detail":"first"}\n\n',
        'event: text\ndata: {"detail":"second"}\n\n',
      ],
      cancel,
    );
    const uiError = new Error('UI update failed');

    await expect(
      sendChatStreamApi({
        message: 'test',
        onEvent: () => {
          throw uiError;
        },
      }),
    ).rejects.toBe(uiError);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(response.body?.locked).toBe(false);
  });

  it('服务端 error 帧进入 reject，done 缺最终消息也 reject', async () => {
    mockStreamResponse([
      'event: error\ndata: {"message":"Backend failure"}\n\n',
    ]);
    await expect(
      sendChatStreamApi({ message: 'test', onEvent: () => {} }),
    ).rejects.toThrow('Backend failure');

    mockStreamResponse(['event: done\ndata: {"total_tokens":1}\n\n']);
    await expect(
      sendChatStreamApi({ message: 'test', onEvent: () => {} }),
    ).rejects.toThrow('did not include the final assistant message');
  });
});
