import uuid

from django.conf import settings
from django.db import models


class Skill(models.Model):
    """Skill 主体：名称全表唯一，标签与上传者挂在 Skill 上。"""

    name = models.CharField(max_length=64, unique=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tags = models.JSONField(default=list, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='skill_hub_skills',
    )
    published_version = models.ForeignKey(
        'SkillVersion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'skill_hub_skills'
        indexes = [
            models.Index(fields=['-updated_at', '-id'], name='skill_hub_updated_idx'),
            models.Index(
                fields=['owner', '-updated_at', '-id'],
                name='skill_hub_owner_updated_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(name__regex=r'^[a-z0-9]+(?:-[a-z0-9]+)*$'),
                name='skill_hub_name_valid',
            ),
        ]

    def __str__(self):
        return self.name


class SkillVersion(models.Model):
    """Skill 的一个版本，对应一个规范化 ZIP 文件，内容不可变。"""

    class Status(models.TextChoices):
        READY = 'ready'
        DELETING = 'deleting'

    class SourceType(models.TextChoices):
        SKILL_MD = 'skill_md'
        ARCHIVE = 'archive'

    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='versions',
    )
    version = models.CharField(max_length=32)
    description = models.CharField(max_length=1024)
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    original_filename = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=512, unique=True)
    archive_name = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    file_count = models.PositiveIntegerField()
    files = models.JSONField(default=list)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.READY,
    )
    error_message = models.TextField(blank=True, default='')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='skill_hub_versions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'skill_hub_skill_versions'
        constraints = [
            models.UniqueConstraint(
                fields=['skill', 'version'],
                name='uniq_skill_hub_skill_version',
            ),
            models.CheckConstraint(
                condition=models.Q(version__regex=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$'),
                name='skill_hub_version_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0),
                name='skill_hub_size_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(file_count__gt=0),
                name='skill_hub_file_count_positive',
            ),
        ]
        indexes = [
            models.Index(
                fields=['skill', '-created_at', '-id'],
                name='skill_hub_version_created_idx',
            ),
            models.Index(
                fields=['status', 'created_at'],
                name='skill_hub_version_status_idx',
            ),
        ]

    def __str__(self):
        return f'{self.skill.name}@{self.version}'
