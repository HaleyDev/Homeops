import { describe, expect, it } from 'vitest';

import type { ChatMessage } from '../types';

import {
  applyAssistantStreamEvent,
  applyFinalAssistantMessage,
  finishIncompleteAssistantMessage,
  mergeToolCall,
  normalizeChatMessage,
  normalizeToolCall,
  summarizeToolUsage,
} from '../message-utils';

function createStreamingMessage(uiKey = 'local-assistant'): ChatMessage {
  return normalizeChatMessage(
    { role: 'assistant', content: '' },
    { loading: true, streaming: true, uiKey },
  );
}

describe('AI 助手消息归一化', () => {
  it('兼容只有 name/args 的旧工具记录，不伪造成功状态', () => {
    const message = normalizeChatMessage(
      {
        id: 42,
        role: 'assistant',
        content: '历史回复',
        tool_calls: [{ name: 'get_server_status', args: { server: 'backend' } }],
      },
      { uiKey: 'history-42' },
    );

    expect(message.uiKey).toBe('history-42');
    expect(message.key).toBe('history-42');
    expect(message.processExpanded).toBe(false);
    expect(message.streaming).toBe(false);
    expect(message.toolCalls).toHaveLength(1);
    expect(message.toolCalls[0]).toEqual({
      args: { server: 'backend' },
      id: 'legacy-42-0',
      name: 'get_server_status',
    });
    expect(message.toolCalls[0]?.status).toBeUndefined();
    expect(message.toolCalls[0]).not.toHaveProperty('result');
  });

  it('缺省消息字段也有稳定 UI 状态和 legacy 渲染 id', () => {
    const tool = normalizeToolCall({ name: 'legacy_tool' }, 2, 'local-1');
    expect(tool).toEqual({
      args: {},
      id: 'legacy-local-1-2',
      name: 'legacy_tool',
    });
  });
});

describe('AI 工具调用合并', () => {
  it('tool_response 按 id 更新且不重复，重复响应也保持一条记录', () => {
    const called = mergeToolCall(
      [],
      {
        id: 'call-1',
        name: 'get_server_status',
        args: { server: 'backend' },
        status: 'running',
      },
      'tool_call',
      'local-1',
    );
    const responded = mergeToolCall(
      called,
      {
        id: 'call-1',
        name: 'get_server_status',
        result: { state: 'running' },
        status: 'success',
      },
      'tool_response',
      'local-1',
    );
    const repeated = mergeToolCall(
      responded,
      {
        id: 'call-1',
        name: 'get_server_status',
        result: { state: 'running' },
        status: 'success',
      },
      'tool_response',
      'local-1',
    );

    expect(repeated).toHaveLength(1);
    expect(repeated[0]).toEqual({
      args: { server: 'backend' },
      id: 'call-1',
      name: 'get_server_status',
      result: { state: 'running' },
      status: 'success',
    });
  });

  it('同名重复调用保留顺序，并按各自 id 配对', () => {
    let calls = mergeToolCall(
      [],
      { id: 'call-1', name: 'status', status: 'running' },
      'tool_call',
      'local-1',
    );
    calls = mergeToolCall(
      calls,
      { id: 'call-2', name: 'status', status: 'running' },
      'tool_call',
      'local-1',
    );
    calls = mergeToolCall(
      calls,
      { id: 'call-2', name: 'status', result: 'second', status: 'success' },
      'tool_response',
      'local-1',
    );
    calls = mergeToolCall(
      calls,
      { id: 'call-1', name: 'status', result: 'first', status: 'error' },
      'tool_response',
      'local-1',
    );

    expect(calls.map((call) => call.id)).toEqual(['call-1', 'call-2']);
    expect(calls.map((call) => call.result)).toEqual(['first', 'second']);
    expect(summarizeToolUsage(calls)).toEqual([
      {
        count: 2,
        firstCallId: 'call-1',
        hasError: true,
        name: 'status',
        status: 'error',
      },
    ]);
  });

  it('兼容无 id 响应，从后向前配合同名 running 调用', () => {
    let calls = mergeToolCall(
      [],
      { id: 'call-1', name: 'status', status: 'running' },
      'tool_call',
      'local-1',
    );
    calls = mergeToolCall(
      calls,
      { id: 'call-2', name: 'status', status: 'running' },
      'tool_call',
      'local-1',
    );
    calls = mergeToolCall(
      calls,
      { name: 'status', result: { ok: true }, status: 'success' },
      'tool_response',
      'local-1',
    );

    expect(calls[0]?.status).toBe('running');
    expect(calls[1]).toMatchObject({
      id: 'call-2',
      result: { ok: true },
      status: 'success',
    });
  });
});

describe('AI 流式消息生命周期', () => {
  it('正文首段只关闭 Bubble loading，不结束整轮 streaming', () => {
    const message = createStreamingMessage();
    applyAssistantStreamEvent(message, {
      event: 'thinking',
      data: { detail: '先查询' },
    });
    applyAssistantStreamEvent(message, {
      event: 'text',
      data: { detail: '正文第一段' },
    });

    expect(message.thinking).toBe('先查询');
    expect(message.content).toBe('正文第一段');
    expect(message.loading).toBe(false);
    expect(message.streaming).toBe(true);
    expect(message.processExpanded).toBe(false);
  });

  it('done 用最终消息校准，同时保留 uiKey 和用户展开状态', () => {
    const message = createStreamingMessage('stable-ui-key');
    message.processExpanded = true;
    message.content = '临时正文';
    applyFinalAssistantMessage(message, {
      id: 99,
      role: 'assistant',
      content: '最终正文',
      thinking: '最终思考',
      tool_calls: [
        {
          id: 'call-1',
          name: 'status',
          args: {},
          result: { ok: true },
          status: 'success',
        },
      ],
      created_at: '2026-11-14T12:00:00Z',
    });

    expect(message).toMatchObject({
      id: 99,
      key: 'stable-ui-key',
      uiKey: 'stable-ui-key',
      content: '最终正文',
      thinking: '最终思考',
      processExpanded: true,
      loading: false,
      streaming: false,
    });
    expect(message.toolCalls).toHaveLength(1);
  });

  it('异常结束将 running 标为 incomplete，而不是 success', () => {
    const message = createStreamingMessage();
    applyAssistantStreamEvent(message, {
      event: 'tool_call',
      data: { id: 'call-1', name: 'status', status: 'running' },
    });
    finishIncompleteAssistantMessage(message, '连接中断');

    expect(message.streaming).toBe(false);
    expect(message.loading).toBe(false);
    expect(message.streamError).toBe('连接中断');
    expect(message.toolCalls[0]?.status).toBe('incomplete');
  });
});
