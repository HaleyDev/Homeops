"""SKILL.md frontmatter、版本号与标签的纯函数校验，不接触数据库和磁盘。"""

import re
from dataclasses import dataclass, field

import yaml

NAME_PATTERN = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
VERSION_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$')
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_TAGS = 20
MAX_TAG_LENGTH = 32


@dataclass
class Issue:
    field: str
    code: str
    message: str

    def as_dict(self):
        return {'field': self.field, 'code': self.code, 'message': self.message}


@dataclass
class SkillMetadata:
    name: str = ''
    description: str = ''
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def valid(self):
        return not self.errors


class _UniqueKeyLoader(yaml.SafeLoader):
    """拒绝重复键的安全 YAML loader，不构造任意 Python 对象。"""


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f'Duplicate frontmatter key: {key}')
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _split_frontmatter(text):
    """返回 (frontmatter 文本, 正文)；缺失分隔符时抛出 ValueError。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        raise ValueError('SKILL.md must start with YAML frontmatter delimited by ---.')
    for index in range(1, len(lines)):
        if lines[index].strip() == '---':
            return '\n'.join(lines[1:index]), '\n'.join(lines[index + 1:])
    raise ValueError('SKILL.md frontmatter is missing the closing --- delimiter.')


def parse_skill_md(data):
    """解析并校验 SKILL.md 内容，返回 SkillMetadata（含错误与警告）。"""
    metadata = SkillMetadata()
    if not data:
        metadata.errors.append(Issue('file', 'empty_file', 'File content is empty.'))
        return metadata
    if b'\x00' in data:
        metadata.errors.append(Issue('file', 'nul_byte', 'File contains a NUL byte.'))
        return metadata
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        metadata.errors.append(
            Issue('file', 'invalid_utf8', 'File must be valid UTF-8 text.')
        )
        return metadata

    try:
        frontmatter_text, body = _split_frontmatter(text)
    except ValueError as exc:
        metadata.errors.append(Issue('frontmatter', 'invalid_frontmatter', str(exc)))
        return metadata

    try:
        frontmatter = yaml.load(frontmatter_text, Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        metadata.errors.append(Issue('frontmatter', 'invalid_yaml', str(exc)))
        return metadata
    if not isinstance(frontmatter, dict):
        metadata.errors.append(
            Issue('frontmatter', 'invalid_frontmatter', 'Frontmatter must be a mapping.')
        )
        return metadata

    name = frontmatter.get('name')
    if not isinstance(name, str) or not name:
        metadata.errors.append(
            Issue('name', 'invalid_name', 'name is required and must be a string.')
        )
    elif len(name) > MAX_NAME_LENGTH or not NAME_PATTERN.fullmatch(name):
        metadata.errors.append(
            Issue(
                'name',
                'invalid_name',
                'name must contain only lowercase letters, numbers, and single hyphens, and be 1-64 characters long.',
            )
        )
    else:
        metadata.name = name

    description = frontmatter.get('description')
    if not isinstance(description, str) or not description.strip():
        metadata.errors.append(
            Issue(
                'description',
                'invalid_description',
                'description is required and must not be blank.',
            )
        )
    elif len(description.strip()) > MAX_DESCRIPTION_LENGTH:
        metadata.errors.append(
            Issue(
                'description',
                'invalid_description',
                'description must not exceed 1024 characters.',
            )
        )
    else:
        metadata.description = description.strip()

    if not body.strip():
        metadata.warnings.append(
            Issue('body', 'empty_body', 'SKILL.md body is empty after frontmatter.')
        )
    return metadata


def validate_version(version):
    """校验用户指定的版本号，返回 Issue 或 None。"""
    if not isinstance(version, str) or not version:
        return Issue('version', 'invalid_version', 'Version is required.')
    if len(version) > 32 or not VERSION_PATTERN.fullmatch(version):
        return Issue(
            'version',
            'invalid_version',
            'Version may contain only letters, numbers, dots, underscores, and hyphens; it must start with a letter or number and be 1-32 characters long.',
        )
    return None


def normalize_tags(raw_tags):
    """规范化标签列表，返回 (tags, errors)。按忽略大小写去重，保留首见。"""
    errors = []
    if raw_tags is None:
        return [], errors
    if not isinstance(raw_tags, list):
        return [], [Issue('tags', 'invalid_tags', 'Tags must be an array of strings.')]
    if len(raw_tags) > MAX_TAGS:
        errors.append(Issue('tags', 'too_many_tags', 'Each Skill may have at most 20 tags.'))
        return [], errors
    tags = []
    seen = set()
    for item in raw_tags:
        if not isinstance(item, str):
            errors.append(Issue('tags', 'invalid_tag', 'Each tag must be a string.'))
            continue
        tag = item.strip()
        if not tag or len(tag) > MAX_TAG_LENGTH or any(ord(ch) < 32 for ch in tag):
            errors.append(
                Issue(
                    'tags',
                    'invalid_tag',
                    'Each tag must be 1-32 characters long after trimming and must not contain control characters.',
                )
            )
            continue
        lowered = tag.lower()
        if lowered not in seen:
            seen.add(lowered)
            tags.append(tag)
    return tags, errors
