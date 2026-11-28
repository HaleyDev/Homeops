import { describe, expect, it } from 'vitest';

import skillHubRoutes from '#/router/routes/modules/skill-hub';

import {
  buildInstallPrompt,
  extractSkillUploadErrors,
  MAX_SKILL_FILE_SIZE,
  validateSkillFile,
  validateSkillTags,
  validateSkillVersion,
} from '../skill-hub-utils';

describe('skill hub 文件与表单校验', () => {
  it('接受 SKILL.md 和四种压缩格式并拒绝危险基础输入', () => {
    for (const name of [
      'SKILL.md',
      'skill.md',
      'skill.zip',
      'skill.tar',
      'skill.tar.gz',
      'skill.tgz',
    ]) {
      expect(validateSkillFile({ name, size: 1 })).toBeNull();
    }
    expect(validateSkillFile({ name: 'other.md', size: 1 })).toContain(
      'SKILL.md',
    );
    expect(validateSkillFile({ name: 'skill.pdf', size: 1 })).toContain(
      '仅支持',
    );
    expect(validateSkillFile({ name: 'SKILL.md', size: 0 })).toContain(
      '空文件',
    );
    expect(
      validateSkillFile({ name: 'skill.zip', size: MAX_SKILL_FILE_SIZE + 1 }),
    ).toContain('10 MiB');
  });

  it('校验用户版本号和标签数量长度', () => {
    expect(validateSkillVersion('v1.2.3')).toBeNull();
    expect(validateSkillVersion('release_candidate-2')).toBeNull();
    expect(validateSkillVersion('')).toContain('请填写版本号');
    expect(validateSkillVersion('.hidden')).not.toBeNull();
    expect(validateSkillVersion('a'.repeat(33))).not.toBeNull();
    expect(validateSkillTags(['Ops', '值班'])).toBeNull();
    expect(
      validateSkillTags(Array.from({ length: 21 }, () => 'tag')),
    ).toContain('20');
    expect(validateSkillTags([''])).not.toBeNull();
  });

  it('从正式上传错误中提取字段错误并去重', () => {
    const error = {
      response: {
        data: {
          detail: '版本冲突',
          errors: [{ message: 'name 不合法' }, { message: '版本冲突' }],
          version: ['版本冲突'],
        },
      },
    };
    expect(extractSkillUploadErrors(error)).toEqual([
      'name 不合法',
      '版本冲突',
    ]);
  });
});

describe('skill hub 安装提示语', () => {
  it('按名称排序去重并生成 Discovery、安装和列表命令', () => {
    const prompt = buildInstallPrompt(
      [
        { name: 'zeta-skill' },
        { name: 'alpha-skill' },
        { name: 'alpha-skill' },
      ],
      'https://homeops.example.com/',
    );

    expect(prompt.indexOf('alpha-skill')).toBeLessThan(
      prompt.indexOf('zeta-skill'),
    );
    expect(prompt).toContain(
      'https://homeops.example.com/.well-known/skills/index.json',
    );
    expect(prompt).toContain(
      'npx skills add "https://homeops.example.com" --skill alpha-skill --skill zeta-skill',
    );
    expect(prompt).toContain('-a "<你识别出的Agent类型>" -y');
    expect(prompt).toContain(
      'npx skills add "https://homeops.example.com" --list',
    );
    expect(prompt).toContain(
      '将项目根目录下的 skills-lock.json 和本次安装的 Skill 对应目录添加到项目根目录的 .gitignore 中',
    );
    expect(prompt).not.toContain('git clone');
  });
});

describe('skill hub 菜单', () => {
  it('注册所有登录用户可访问的顶层页面', () => {
    expect(skillHubRoutes).toHaveLength(1);
    expect(skillHubRoutes[0]).toMatchObject({
      name: 'SkillHub',
      path: '/skill-hub',
      meta: {
        icon: 'lucide:package-open',
        title: 'page.skillHub',
      },
    });
    expect(skillHubRoutes[0]?.meta?.authority).toBeUndefined();
  });
});
