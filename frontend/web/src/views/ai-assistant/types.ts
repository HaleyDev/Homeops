import type { BubbleListItemProps } from 'vue-element-plus-x/types/BubbleList';

import type { ChatToolCallStatus } from '#/api/ai';

/** AI 助手页面类型定义。消息可直接透传给 BubbleList。 */

export type ChatRole = 'ai' | 'user';

/** 页面统一使用的工具记录；status 缺省表示无法确认的旧历史记录。 */
export interface AssistantToolCall {
  args: Record<string, unknown>;
  id: string;
  name: string;
  result?: unknown;
  status?: ChatToolCallStatus;
}

/** 聊天消息(BubbleList 列表项)。uiKey 不随 done 返回数据库 id 而改变。 */
export type ChatMessage = BubbleListItemProps & {
  content: string;
  createdAt?: string;
  id?: number | string;
  key: string;
  processExpanded: boolean;
  role: ChatRole;
  streamError?: string;
  streaming: boolean;
  thinking: string;
  toolCalls: AssistantToolCall[];
  uiKey: string;
};

/** 左侧会话列表项(字段与后端 ChatSession 对齐)。 */
export interface ChatConversation {
  session_id: string;
  title: string;
}
