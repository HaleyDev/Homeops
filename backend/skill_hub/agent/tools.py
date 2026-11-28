import logging
from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import DatabaseError

from ..models import Skill
from ..services import published_version

logger = logging.getLogger(__name__)


def _error(message):
    return {'status': 'error', 'error_message': message}


def _published_skill_items():
    skills = Skill.objects.select_related('published_version').prefetch_related(
        'versions'
    )
    items = []
    for skill in skills.order_by('name'):
        published = published_version(skill)
        if published is None:
            continue
        items.append(
            {
                'name': skill.name,
                'description': published.description,
                'current_version': published.version,
                'source_type': published.source_type,
                'tags': list(skill.tags or []),
                'files': list(published.files or []),
            }
        )
    return items


def _list_available_skills():
    try:
        items = _published_skill_items()
    except DatabaseError:
        logger.exception('Skill Hub list query failed')
        return _error('The Skill list is temporarily unavailable. Please try again.')
    return {'status': 'success', 'total': len(items), 'items': items}


def _normalize_skill_names(skill_names):
    if not isinstance(skill_names, list) or not skill_names:
        return None
    names = []
    for name in skill_names:
        if not isinstance(name, str) or not name.strip():
            return None
        normalized = name.strip()
        if normalized not in names:
            names.append(normalized)
    return sorted(names)


def _normalize_source_url(source_url):
    if not isinstance(source_url, str):
        return None
    configured_url = str(getattr(settings, 'FRONTEND_URL', ''))
    source = (source_url.strip() or configured_url).strip().rstrip('/')
    if not source or any(char.isspace() or char == '"' for char in source):
        return None
    try:
        parsed = urlsplit(source)
    except ValueError:
        return None
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return None
    return source


def _build_install_prompt(skills, source):
    names = [skill['name'] for skill in skills]
    skill_arguments = ''.join(f' --skill {name}' for name in names)
    skill_list = '\n'.join(
        f'{index}. {name}' for index, name in enumerate(names, start=1)
    )
    return f'''请为当前项目安装 Skill Hub 上的以下 Agent Skills：

{skill_list}

Skill 源地址（HTTP，无需 Git）：{source}
全部 Skill 索引：{source}/.well-known/skills/index.json

执行前，请先识别你当前所属的 Agent 类型，并映射为 npx skills 支持的 -a 参数。
如果无法确定，请先询问我，不要盲目选择。
只在当前项目中安装，不要使用 -g，也不要改用其他下载来源。

请执行：
npx skills add "{source}"{skill_arguments} -a "<你识别出的Agent类型>" -y

如需先查看平台上的全部可用 Skill，可执行：
npx skills add "{source}" --list

安装完成后，请检查对应 Skill 目录及 SKILL.md 是否存在，并报告每个 Skill 的安装结果。
下载完成后，请将项目根目录下的 skills-lock.json 和本次安装的 Skill 对应目录添加到项目根目录的 .gitignore 中。'''


def _generate_skill_install_prompt(skill_names, source_url):
    names = _normalize_skill_names(skill_names)
    if names is None:
        return _error('skill_names must be a non-empty array of Skill names.')
    source = _normalize_source_url(source_url)
    if source is None:
        return _error(
            'source_url must be a valid HTTP(S) URL, or FRONTEND_URL must be configured.'
        )
    try:
        items = _published_skill_items()
    except DatabaseError:
        logger.exception('Skill Hub prompt query failed')
        return _error('The Skill list is temporarily unavailable. Please try again.')

    items_by_name = {item['name']: item for item in items}
    missing = [name for name in names if name not in items_by_name]
    if missing:
        return _error(
            'These Skills do not exist or have no downloadable published version: '
            f'{", ".join(missing)}. Call list_available_skills to see valid names.'
        )
    selected = [items_by_name[name] for name in names]
    return {
        'status': 'success',
        'source_url': source,
        'skills': selected,
        'prompt': _build_install_prompt(selected, source),
    }


_list_available_skills_async = sync_to_async(
    _list_available_skills,
    thread_sensitive=True,
)
_generate_skill_install_prompt_async = sync_to_async(
    _generate_skill_install_prompt,
    thread_sensitive=True,
)


async def list_available_skills() -> dict:
    """查询 Skill Hub 中当前可发现和下载的全部 Agent Skills。

    只返回存在 ready 发布版本的 Skill，包含名称、发布版本描述、版本号、类型、
    标签和文件清单。用户询问有哪些 Skill 或某个 Skill 是否存在时必须调用。

    Returns:
        dict: status、Skill 总数及按名称排序的 Skill 列表。
    """
    return await _list_available_skills_async()


async def generate_skill_install_prompt(
    skill_names: list[str],
    source_url: str = '',
) -> dict:
    """为指定 Skill 生成可复制给其他 Agent 执行的 HTTP 安装提示语。

    只会为真实存在且有 ready 发布版本的 Skill 生成提示语。用户明确要求安装、
    下载或生成提示语时调用；如果用户未提供名称，应先调用 list_available_skills。

    Args:
        skill_names: 要安装的 Skill 名称列表，会去重并排序，不能为空。
        source_url: Skill Hub 的 HTTP(S) 源地址；留空时使用 FRONTEND_URL。

    Returns:
        dict: status、源地址、所选 Skill 详情及完整安装提示语 prompt。
    """
    return await _generate_skill_install_prompt_async(skill_names, source_url)
