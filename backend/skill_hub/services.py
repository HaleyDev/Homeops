"""Skill Hub 业务编排：dry-run、正式上传、发布版本定位、标签与删除。"""

from django.db import IntegrityError, transaction

from . import storage, validators
from .archives import MAX_UPLOAD_BYTES, collect_skill
from .models import Skill, SkillVersion
from .permissions import can_manage_skill


class PayloadTooLargeError(Exception):
    pass


class ConflictError(Exception):
    pass


class OwnerPermissionError(Exception):
    pass


class InvalidUploadError(Exception):
    def __init__(self, report):
        super().__init__('Skill upload validation failed.')
        self.report = report


def _read_upload(uploaded_file):
    if uploaded_file.size > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError('Uploaded file exceeds the 10 MiB limit.')
    data = uploaded_file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise InvalidUploadError(
            {
                'valid': False,
                'name': '',
                'description': '',
                'source_type': None,
                'file_count': 0,
                'size_bytes': 0,
                'errors': [
                    {'field': 'file', 'code': 'empty_file', 'message': 'File content is empty.'}
                ],
                'warnings': [],
            }
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError('Uploaded file exceeds the 10 MiB limit.')
    return data


def _build_report(original_filename, data):
    """完整校验并生成预览报告，不写数据库、不保存正式文件。"""
    collected = collect_skill(original_filename, data)
    errors = list(collected.errors)
    warnings = []
    name = ''
    description = ''
    if 'SKILL.md' in collected.files:
        metadata = validators.parse_skill_md(collected.files['SKILL.md'])
        errors.extend(metadata.errors)
        warnings.extend(metadata.warnings)
        name = metadata.name
        description = metadata.description
        if collected.directory and metadata.name and collected.directory != metadata.name:
            errors.append(
                validators.Issue(
                    'name',
                    'directory_mismatch',
                    f'Skill directory "{collected.directory}" must match the frontmatter name.',
                )
            )
    report = {
        'valid': not errors,
        'name': name,
        'description': description,
        'source_type': collected.source_type or None,
        'file_count': len(collected.files),
        'size_bytes': len(data),
        'errors': [issue.as_dict() for issue in errors],
        'warnings': [issue.as_dict() for issue in warnings],
    }
    return report, collected


def dry_run(uploaded_file):
    report, _ = _build_report(uploaded_file.name, _read_upload(uploaded_file))
    return report


def _cleanup_orphan(storage_key):
    """数据库写入失败时清理孤立文件；并发下已有记录的同名文件不删。"""
    if storage_key and not SkillVersion.objects.filter(storage_key=storage_key).exists():
        storage.delete_zip(storage_key)


def upload_skill(uploaded_file, version, raw_tags, user):
    """正式上传：重新完整校验，按 name 归属 Skill，追加不可变版本。"""
    data = _read_upload(uploaded_file)
    report, collected = _build_report(uploaded_file.name, data)

    version_issue = validators.validate_version(version)
    if version_issue:
        report['errors'].append(version_issue.as_dict())
    tags, tag_errors = validators.normalize_tags(raw_tags)
    report['errors'].extend(issue.as_dict() for issue in tag_errors)
    if not report['valid'] or report['errors']:
        report['valid'] = False
        raise InvalidUploadError(report)

    name = report['name']
    zip_bytes = storage.build_zip(name, collected.files)
    if len(zip_bytes) > MAX_UPLOAD_BYTES:
        report['valid'] = False
        report['errors'].append(
            {
                'field': 'file',
                'code': 'archive_too_large',
                'message': 'Normalized ZIP exceeds the 10 MiB limit.',
            }
        )
        raise InvalidUploadError(report)

    storage_key = None
    try:
        with transaction.atomic():
            skill = Skill.objects.select_for_update().filter(name=name).first()
            if skill is not None:
                if not can_manage_skill(user, skill):
                    raise OwnerPermissionError(
                        'Only the owner or a superuser can upload a new version.'
                    )
                if skill.versions.filter(version=version).exists():
                    raise ConflictError(
                        'This version already exists for the Skill. Use a different version.'
                    )
                update_fields = ['updated_at']
                if raw_tags is not None:
                    skill.tags = tags
                    update_fields.append('tags')
                skill.save(update_fields=update_fields)
            else:
                skill = Skill(name=name, owner=user, tags=tags)
                skill.save()

            storage_key = storage.save_zip(skill.uuid, version, zip_bytes)
            version = SkillVersion.objects.create(
                skill=skill,
                version=version,
                description=report['description'],
                source_type=collected.source_type,
                original_filename=(uploaded_file.name or '')[:255],
                storage_key=storage_key,
                archive_name=f'{name}-{version}.zip',
                size_bytes=len(zip_bytes),
                sha256=storage.sha256_hex(zip_bytes),
                file_count=len(collected.files),
                files=sorted(collected.files),
                uploaded_by=user,
            )
            skill.published_version = version
            skill.save(update_fields=['published_version', 'updated_at'])
            return version
    except IntegrityError as exc:
        _cleanup_orphan(storage_key)
        raise ConflictError(
            'The Skill name or version conflicts with an existing record. Refresh and try again.'
        ) from exc
    except Exception:
        _cleanup_orphan(storage_key)
        raise


def _latest_ready_version(skill):
    return (
        skill.versions.filter(status=SkillVersion.Status.READY)
        .order_by('-created_at', '-id')
        .first()
    )


def published_version(skill):
    """优先使用显式发布版本，兼容迁移前仅按最新上传排序的数据。"""
    if skill.published_version_id:
        selected = skill.published_version
        if selected.skill_id == skill.id and selected.status == SkillVersion.Status.READY:
            return selected
    return _latest_ready_version(skill)


def publish_version(skill, version_number):
    """按 Skill 名称下的版本号切换发布版本。"""
    with transaction.atomic():
        locked_skill = Skill.objects.select_for_update().get(pk=skill.pk)
        version = locked_skill.versions.filter(
            version=version_number, status=SkillVersion.Status.READY
        ).first()
        if version is None:
            raise SkillVersion.DoesNotExist(version_number)
        locked_skill.published_version = version
        locked_skill.save(update_fields=['published_version', 'updated_at'])
        return version


def update_tags(skill, tags):
    skill.tags = tags
    skill.save(update_fields=['tags', 'updated_at'])
    return skill


def tag_summary():
    """全部去重标签及对应 Skill 数量，供前端筛选下拉。"""
    counts = {}
    for tags in Skill.objects.values_list('tags', flat=True):
        for tag in tags or []:
            counts[tag] = counts.get(tag, 0) + 1
    return [{'name': tag, 'count': counts[tag]} for tag in sorted(counts)]


def _delete_version(version):
    version.status = SkillVersion.Status.DELETING
    version.save(update_fields=['status'])
    try:
        storage.delete_zip(version.storage_key)
    except OSError:
        version.error_message = 'Failed to delete the file. Please try again.'
        version.save(update_fields=['error_message'])
        return False
    version.delete()
    return True


def _cleanup_skill_if_empty(skill):
    if not skill.versions.exists():
        storage.cleanup_skill_dir(skill.uuid)
        skill.delete()


def delete_skill(skill):
    """删除整个 Skill：全部版本逐个清理，最后删除 Skill 记录与目录。"""
    for version in list(skill.versions.all()):
        _delete_version(version)
    _cleanup_skill_if_empty(skill)


def delete_version(skill, version_number):
    version = skill.versions.filter(version=version_number).first()
    if version is None:
        raise SkillVersion.DoesNotExist(version_number)
    current = published_version(skill)
    was_current = current is not None and current.id == version.id
    _delete_version(version)
    if was_current:
        skill.refresh_from_db(fields=['published_version'])
        skill.published_version = _latest_ready_version(skill)
        skill.save(update_fields=['published_version', 'updated_at'])
    _cleanup_skill_if_empty(skill)
