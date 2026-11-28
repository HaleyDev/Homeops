"""规范化 ZIP 的构建、原子保存、删除与单文件读取。"""

import hashlib
import io
import os
import shutil
import uuid as uuid_lib
import zipfile
from pathlib import Path

from django.conf import settings


def get_root():
    root = Path(settings.SKILL_HUB_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_key(storage_key):
    """解析存储键并确保结果仍位于根目录内。"""
    root = get_root()
    path = (root / storage_key).resolve()
    if root.resolve() not in path.parents:
        raise ValueError('Storage key resolves outside the Skill Hub root.')
    return path


def build_zip(name, files):
    """把收集到的文件规范化为 <name>/... 的 ZIP 字节内容。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(f'{name}/{path}', files[path])
    return buffer.getvalue()


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def save_zip(skill_uuid, version, data):
    """先写同文件系统临时目录，再原子重命名为正式文件，返回 storage_key。"""
    storage_key = f'{skill_uuid}/{version}.zip'
    final_path = resolve_key(storage_key)
    tmp_dir = get_root() / '.tmp' / uuid_lib.uuid4().hex
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        tmp_path = tmp_dir / 'skill.zip'
        tmp_path.write_bytes(data)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, final_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return storage_key


def delete_zip(storage_key):
    """删除文件；文件不存在视为成功。"""
    path = resolve_key(storage_key)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def cleanup_skill_dir(skill_uuid):
    """Skill 全部版本删除后清理其存储目录。"""
    shutil.rmtree(get_root() / str(skill_uuid), ignore_errors=True)


def read_entry(storage_key, name, relative_path):
    """从规范化 ZIP 中读取 <name>/<relative_path> 的内容，不存在返回 None。"""
    path = resolve_key(storage_key)
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.read(f'{name}/{relative_path}')
    except (FileNotFoundError, KeyError, zipfile.BadZipFile):
        return None
