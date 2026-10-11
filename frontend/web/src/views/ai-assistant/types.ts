import type { BubbleListItemProps } from 'vue-element-plus-x/types/BubbleList';

/**
 * AI 助手页面类型定义
 * 消息类型在 vue-element-plus-x 的气泡项基础上扩展业务字段,
 * 可直接透传给 BubbleList 的 list 项。
 */

/** 消息角色 */
export type ChatRole = 'user' | 'ai';

/** 聊天消息(BubbleList 列表项) */
export type ChatMessage = BubbleListItemProps & {
  key: string;
  role: ChatRole;
};

/** 左侧会话列表项 */
export type ChatConversation = {
  id: string;
  label: string;
};
