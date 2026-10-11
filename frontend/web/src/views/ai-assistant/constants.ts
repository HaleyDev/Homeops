/**
 * AI 助手页面常量与默认数据。
 *
 * 会话列表仍为本地默认数据(后端暂无会话列表接口,只有对话接口);
 * 对话已对接真实接口 POST /api/ai/chat/(见 src/api/ai)。
 */
import type { ChatConversation, ChatMessage } from './types';

/** AI 头像(内联 SVG,无外网依赖) */
export const AI_AVATAR = buildSvgAvatar('#3b82f6', '🤖');

/** 用户头像(内联 SVG,无外网依赖) */
export const USER_AVATAR = buildSvgAvatar('#10b981', '🧑');

/** 默认会话列表 */
export function createDefaultConversations(): ChatConversation[] {
  return [{ id: 'conv-new', label: '新会话' }];
}

/** 页面初始欢迎消息 */
export function createWelcomeMessage(): ChatMessage {
  return {
    key: 'msg-welcome',
    role: 'ai',
    placement: 'start',
    variant: 'filled',
    shape: 'round',
    avatar: AI_AVATAR,
    content: '你好,我是 AI 助手。输入问题即可开始对话。',
  };
}

/** 生成内联 SVG 头像(data URI,避免外链图片依赖) */
function buildSvgAvatar(bg: string, emoji: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="24" fill="${bg}"/><text x="24" y="33" font-size="22" text-anchor="middle">${emoji}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
