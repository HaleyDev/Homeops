"""DRF 输出序列化：列表项与版本的下载信息均按发布版本计算。

name/description 只读，来自文件解析结果，不提供任何写入字段。
"""

from rest_framework import serializers

from .permissions import can_manage_skill
from .services import published_version


def _user_brief(user):
    if user is None:
        return None
    return {'id': user.id, 'username': user.username}


class SkillListSerializer(serializers.BaseSerializer):
    """Skill 列表项：描述、大小、哈希和下载地址均取自发布版本。"""

    def to_representation(self, skill):
        request = self.context['request']
        published = published_version(skill)
        return {
            'id': skill.id,
            'name': skill.name,
            'description': published.description if published else '',
            'current_version': published.version if published else None,
            'source_type': published.source_type if published else None,
            'version_count': skill.versions.count(),
            'tags': skill.tags,
            'size_bytes': published.size_bytes if published else 0,
            'sha256': published.sha256 if published else '',
            'file_count': published.file_count if published else 0,
            'status': published.status if published else 'empty',
            'owner': _user_brief(skill.owner),
            'can_manage': can_manage_skill(request.user, skill),
            'download_path': (
                f'/api/skill-hub/skills/{skill.name}/download/' if published else None
            ),
            'created_at': skill.created_at.isoformat(),
            'updated_at': skill.updated_at.isoformat(),
        }


class SkillVersionSerializer(serializers.BaseSerializer):
    """版本输出：is_current 由 context 中的 published_version_id 决定。"""

    def to_representation(self, version):
        published_id = self.context.get('published_version_id')
        return {
            'version': version.version,
            'description': version.description,
            'source_type': version.source_type,
            'original_filename': version.original_filename,
            'size_bytes': version.size_bytes,
            'file_count': version.file_count,
            'sha256': version.sha256,
            'files': version.files,
            'status': version.status,
            'uploaded_by': _user_brief(version.uploaded_by),
            'created_at': version.created_at.isoformat(),
            'is_current': version.id == published_id,
            'download_path': (
                f'/api/skill-hub/skills/{version.skill.name}'
                f'/versions/{version.version}/download/'
            ),
        }
