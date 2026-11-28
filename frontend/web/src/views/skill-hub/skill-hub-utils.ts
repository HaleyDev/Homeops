import type { Skill, SkillSourceType } from '#/api/skill-hub';

export const MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024;
export const SKILL_VERSION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/;

export function validateSkillFile(file: { name: string; size: number }) {
  const lowerName = file.name.toLowerCase();
  const isArchive = /\.(tar\.gz|tgz|zip|tar)$/i.test(lowerName);
  if (lowerName.endsWith('.md') && lowerName !== 'skill.md') {
    return 'Markdown 文件必须命名为 SKILL.md';
  }
  if (lowerName !== 'skill.md' && !isArchive) {
    return '仅支持 SKILL.md 或 .zip/.tar/.tar.gz/.tgz 压缩包';
  }
  if (file.size === 0) return '不能上传空文件';
  if (file.size > MAX_SKILL_FILE_SIZE) return '文件大小不能超过 10 MiB';
  return null;
}

export function validateSkillVersion(version: string) {
  if (!version) return '请填写版本号';
  if (!SKILL_VERSION_PATTERN.test(version)) {
    return '版本号须以字母或数字开头，仅含字母、数字、点、下划线和连字符，长度 1～32';
  }
  return null;
}

export function validateSkillTags(tags: string[]) {
  if (tags.length > 20) return '每个 Skill 最多 20 个标签';
  if (tags.some((tag) => !tag.trim() || tag.trim().length > 32)) {
    return '每个标签去除空白后长度须为 1～32 个字符';
  }
  return null;
}

export function formatSkillSize(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
}

export function formatSkillSourceType(sourceType: null | SkillSourceType) {
  if (sourceType === 'skill_md') return 'Markdown 单文件';
  if (sourceType === 'archive') return '压缩包';
  return '—';
}

export function formatSkillTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export function buildInstallPrompt(
  skills: Array<Pick<Skill, 'name'>>,
  origin: string,
) {
  const source = origin.replace(/\/$/, '');
  const names = [...new Set(skills.map((skill) => skill.name))].toSorted();
  const skillArguments = names.map((name) => ` --skill ${name}`).join('');
  return `请为当前项目安装 Skill Hub 上的以下 Agent Skills：

${names.map((name, index) => `${index + 1}. ${name}`).join('\n')}

Skill 源地址（HTTP，无需 Git）：${source}
全部 Skill 索引：${source}/.well-known/skills/index.json

执行前，请先识别你当前所属的 Agent 类型，并映射为 npx skills 支持的 -a 参数。
如果无法确定，请先询问我，不要盲目选择。
只在当前项目中安装，不要使用 -g，也不要改用其他下载来源。

请执行：
npx skills add "${source}"${skillArguments} -a "<你识别出的Agent类型>" -y

如需先查看平台上的全部可用 Skill，可执行：
npx skills add "${source}" --list

安装完成后，请检查对应 Skill 目录及 SKILL.md 是否存在，并报告每个 Skill 的安装结果。
下载完成后，请将项目根目录下的 skills-lock.json 和本次安装的 Skill 对应目录添加到项目根目录的 .gitignore 中。`;
}

export function extractSkillUploadErrors(error: unknown) {
  if (!error || typeof error !== 'object') return [];
  const response = (error as { response?: { data?: unknown } }).response;
  const payload = (response?.data ?? (error as { data?: unknown }).data) as
    | {
        detail?: unknown;
        errors?: unknown;
        tags?: unknown;
        version?: unknown;
      }
    | undefined;
  if (!payload || typeof payload !== 'object') return [];
  const messages: string[] = [];
  if (Array.isArray(payload.errors)) {
    for (const issue of payload.errors) {
      if (issue && typeof issue === 'object' && 'message' in issue) {
        messages.push(String(issue.message));
      }
    }
  }
  for (const value of [payload.version, payload.tags, payload.detail]) {
    if (Array.isArray(value)) messages.push(...value.map(String));
    else if (typeof value === 'string') messages.push(value);
  }
  return [...new Set(messages)];
}
