import codecs
import hashlib
import os
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from django.conf import settings


class StorageError(Exception):
    """原文存储不可用，异常消息不包含服务器路径。"""


class UploadValidationError(Exception):
    """上传文件内容或文件名不合法。"""


class FileSizeLimitError(UploadValidationError):
    """上传文件超过配置大小。"""


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    size_bytes: int
    content_hash: str


class KnowledgeFileStorage:
    def __init__(self, root=None, max_file_size=None):
        self.root = Path(root or settings.KNOWLEDGE_UPLOAD_ROOT).resolve()
        self.max_file_size = max_file_size or settings.KNOWLEDGE_MAX_FILE_SIZE

    @staticmethod
    def clean_original_name(filename):
        basename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        cleaned = "".join(
            character
            for character in basename
            if unicodedata.category(character) != "Cc"
        ).strip()
        if not cleaned:
            raise UploadValidationError("文件名不能为空。")
        if len(cleaned) > 255:
            raise UploadValidationError("文件名不能超过 255 个字符。")

        extension = Path(cleaned).suffix.lower()
        if extension not in {".md", ".txt"}:
            raise UploadValidationError("仅支持 Markdown（.md）或 TXT（.txt）文件。")
        if not cleaned[: -len(extension)].strip(" ."):
            raise UploadValidationError("文件名不能只包含扩展名。")
        return cleaned, extension

    def save(self, uploaded_file, knowledge_base_id, extension):
        storage_key = f"{knowledge_base_id}/{uuid.uuid4().hex}{extension}"
        final_path = self._path_for_key(storage_key)
        temporary_path = None
        digest = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        size_bytes = 0

        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=final_path.parent,
                prefix=".upload-",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                for chunk in uploaded_file.chunks():
                    size_bytes += len(chunk)
                    if size_bytes > self.max_file_size:
                        raise FileSizeLimitError("文件大小不能超过 20 MiB。")
                    if b"\x00" in chunk:
                        raise UploadValidationError("文件不能包含 NUL 字节。")
                    try:
                        decoder.decode(chunk)
                    except UnicodeDecodeError as exc:
                        raise UploadValidationError("文件必须使用有效的 UTF-8 编码。") from exc
                    digest.update(chunk)
                    temporary_file.write(chunk)
                try:
                    decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise UploadValidationError("文件必须使用有效的 UTF-8 编码。") from exc

            if size_bytes == 0:
                raise UploadValidationError("不能上传空文件。")
            os.replace(temporary_path, final_path)
            temporary_path = None
        except UploadValidationError:
            raise
        except OSError as exc:
            raise StorageError("知识库原文目录不可写，请联系管理员。") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

        return StoredFile(
            storage_key=storage_key,
            size_bytes=size_bytes,
            content_hash=digest.hexdigest(),
        )

    def delete(self, storage_key):
        path = self._path_for_key(storage_key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StorageError("原文删除失败，请重试。") from exc

    def _path_for_key(self, storage_key):
        key = PurePosixPath(storage_key)
        if key.is_absolute() or ".." in key.parts or "\\" in storage_key:
            raise StorageError("原文存储键不合法。")
        path = self.root.joinpath(*key.parts).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise StorageError("原文存储键不合法。") from exc
        return path
