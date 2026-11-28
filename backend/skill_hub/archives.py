"""不受信任上传内容的安全读取：单文件与 ZIP/TAR 压缩包。

只读取并收集文件内容，不执行其中任何脚本，不调用 extract/extractall。
所有文件在内存中处理，受上传大小、解压大小和文件数量限制约束。
"""

import io
import stat
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .validators import Issue

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXTRACT_BYTES = 25 * 1024 * 1024
MAX_EXTRACT_FILES = 1000
ARCHIVE_EXTENSIONS = ('.zip', '.tar', '.tar.gz', '.tgz')


@dataclass
class CollectedSkill:
    """收集结果：files 的键为相对 Skill 根目录的路径，含统一的 SKILL.md。"""

    source_type: str = ''
    directory: str = ''
    files: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


def _normalize_path(raw_path):
    """校验并规范化归档内路径，非法时抛出 ValueError。"""
    if not raw_path or '\x00' in raw_path or '\\' in raw_path:
        raise ValueError(f'Invalid path: {raw_path!r}')
    if raw_path.startswith('/'):
        raise ValueError(f'Absolute paths are not allowed: {raw_path!r}')
    parts = PurePosixPath(raw_path).parts
    if '..' in parts:
        raise ValueError(f'Path traversal is not allowed: {raw_path!r}')
    normalized = str(PurePosixPath(raw_path))
    if normalized in ('', '.'):
        raise ValueError(f'Invalid path: {raw_path!r}')
    return normalized


def _locate_skill(entries):
    """entries: {规范化路径: 读取句柄}，定位唯一 SKILL.md 并收集其目录下文件。"""
    skill_md_paths = [
        path for path in entries if PurePosixPath(path).name.lower() == 'skill.md'
    ]
    if not skill_md_paths:
        raise ValueError('SKILL.md was not found in the archive.')
    if len(skill_md_paths) > 1:
        raise ValueError(
            'An archive must contain exactly one Skill; multiple SKILL.md files were found.'
        )

    skill_md_path = skill_md_paths[0]
    root = str(PurePosixPath(skill_md_path).parent)
    root = '' if root == '.' else root
    directory = PurePosixPath(root).name if root else ''

    files = {}
    prefix = f'{root}/' if root else ''
    for path, reader in entries.items():
        if prefix and not path.startswith(prefix):
            continue
        relative = path[len(prefix):] if prefix else path
        if not relative:
            continue
        key = 'SKILL.md' if path == skill_md_path else relative
        if key in files:
            raise ValueError(f'Duplicate file path after normalization: {key}')
        files[key] = reader()
    return directory, files


def _collect_archive(data):
    """返回 {规范化路径: callable(读取 bytes)}，并完成安全与限额校验。"""
    errors = []
    if zipfile.is_zipfile(io.BytesIO(data)):
        return _collect_zip(data), errors
    try:
        return _collect_tar(data), errors
    except tarfile.TarError as exc:
        errors.append(Issue('file', 'invalid_archive', f'Failed to parse archive: {exc}'))
        return {}, errors


def _collect_zip(data):
    entries = {}
    total_size = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_EXTRACT_FILES:
            raise ValueError('Archive contains more than 1000 files.')
        for info in infos:
            if info.flag_bits & 0x1:
                raise ValueError('Encrypted ZIP archives are not supported.')
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            # 常见 ZIP 仅记录 0o600 权限而没有文件类型位，应视为普通文件。
            if file_type not in (0, stat.S_IFREG):
                raise ValueError(
                    f'Symbolic links and special files are not allowed: {info.filename}'
                )
            path = _normalize_path(info.filename)
            if path in entries:
                raise ValueError(f'Duplicate archive path: {path}')
            total_size += info.file_size
            if total_size > MAX_EXTRACT_BYTES:
                raise ValueError('Extracted files exceed the 25 MiB total size limit.')
            content = archive.read(info)
            entries[path] = lambda c=content: c
    return entries


def _collect_tar(data):
    entries = {}
    total_size = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        members = archive.getmembers()
        if len([m for m in members if m.isfile()]) > MAX_EXTRACT_FILES:
            raise ValueError('Archive contains more than 1000 files.')
        for member in members:
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                raise ValueError(
                    f'Symbolic links and hard links are not allowed: {member.name}'
                )
            if not member.isfile():
                raise ValueError(f'Special files are not allowed: {member.name}')
            path = _normalize_path(member.name)
            if path in entries:
                raise ValueError(f'Duplicate archive path: {path}')
            total_size += member.size
            if total_size > MAX_EXTRACT_BYTES:
                raise ValueError('Extracted files exceed the 25 MiB total size limit.')
            content = archive.extractfile(member).read()
            entries[path] = lambda c=content: c
    return entries


def collect_skill(original_filename, data):
    """收集上传内容中的 Skill 文件，返回 CollectedSkill。"""
    collected = CollectedSkill()
    lowered = (original_filename or '').lower()
    basename = PurePosixPath(lowered).name

    if basename == 'skill.md':
        collected.source_type = 'skill_md'
        collected.files = {'SKILL.md': data}
        return collected
    if not lowered.endswith(ARCHIVE_EXTENSIONS):
        collected.errors.append(
            Issue(
                'file',
                'unsupported_file',
                'Only SKILL.md or .zip, .tar, .tar.gz, and .tgz archives are supported.',
            )
        )
        return collected

    collected.source_type = 'archive'
    try:
        entries, errors = _collect_archive(data)
        collected.errors.extend(errors)
        if collected.errors:
            return collected
        collected.directory, collected.files = _locate_skill(entries)
    except (ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        collected.errors.append(Issue('file', 'invalid_archive', str(exc)))
    return collected
