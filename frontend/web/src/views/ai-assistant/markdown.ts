import MarkdownIt from 'markdown-it';

/**
 * AI 回复的 markdown 渲染器(页面内共享实例)。
 *
 * - `html: false`(默认):AI 输出中的原始 HTML 会被转义,防注入;
 * - `breaks: true`:单个换行渲染为 <br>,符合聊天场景;
 * - `linkify: true`:纯文本 URL 自动转链接。
 */
const markdown = new MarkdownIt({
  breaks: true,
  linkify: true,
});

/** 渲染 markdown 文本为 HTML 字符串 */
export function renderMarkdown(text: string): string {
  return markdown.render(text ?? '');
}
