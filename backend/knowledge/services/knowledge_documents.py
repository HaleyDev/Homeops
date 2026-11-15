import logging

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from rest_framework.exceptions import APIException, NotFound, ValidationError

from knowledge.models import KnowledgeBase, KnowledgeDocument
from knowledge.storage import (
    FileSizeLimitError,
    KnowledgeFileStorage,
    StorageError,
    UploadValidationError,
)

from . import Conflict

logger = logging.getLogger(__name__)


class FileTooLarge(APIException):
    status_code = 413
    default_detail = "文件大小不能超过 20 MiB。"
    default_code = "file_too_large"


def _storage(storage=None):
    return storage or KnowledgeFileStorage()


def _get_single_file(uploaded_files):
    if set(uploaded_files.keys()) != {"file"}:
        raise ValidationError({"file": "必须且只能上传一个 file 文件字段。"})
    files = uploaded_files.getlist("file")
    if len(files) != 1:
        raise ValidationError({"file": "必须且只能上传一个文件。"})
    return files[0]


def upload_document(knowledge_base_id, uploaded_files, user, storage=None):
    if not KnowledgeBase.objects.filter(pk=knowledge_base_id).exists():
        raise NotFound("知识库不存在。")

    uploaded_file = _get_single_file(uploaded_files)
    storage = _storage(storage)
    try:
        original_name, extension = storage.clean_original_name(uploaded_file.name)
        if uploaded_file.size == 0:
            raise UploadValidationError("不能上传空文件。")
        if uploaded_file.size > settings.KNOWLEDGE_MAX_FILE_SIZE:
            raise FileSizeLimitError("文件大小不能超过 20 MiB。")
    except FileSizeLimitError as exc:
        raise FileTooLarge(str(exc)) from exc
    except UploadValidationError as exc:
        raise ValidationError({"file": str(exc)}) from exc

    try:
        stored_file = storage.save(uploaded_file, knowledge_base_id, extension)
    except FileSizeLimitError as exc:
        raise FileTooLarge(str(exc)) from exc
    except UploadValidationError as exc:
        raise ValidationError({"file": str(exc)}) from exc
    except StorageError as exc:
        raise APIException(str(exc)) from exc

    try:
        try:
            with transaction.atomic():
                knowledge_base = KnowledgeBase.objects.select_for_update().get(
                    pk=knowledge_base_id
                )
                if knowledge_base.documents.filter(
                    content_hash=stored_file.content_hash
                ).exists():
                    raise Conflict("当前知识库已存在相同内容的文件。")
                document = KnowledgeDocument.objects.create(
                    knowledge_base=knowledge_base,
                    original_name=original_name,
                    storage_key=stored_file.storage_key,
                    mime_type="text/markdown" if extension == ".md" else "text/plain",
                    extension=extension,
                    size_bytes=stored_file.size_bytes,
                    content_hash=stored_file.content_hash,
                    created_by=user,
                )
        except KnowledgeBase.DoesNotExist as exc:
            raise NotFound("知识库不存在。") from exc
        except IntegrityError as exc:
            raise Conflict("当前知识库已存在相同内容的文件。") from exc
    except Exception:
        _cleanup_unregistered_file(storage, stored_file, knowledge_base_id)
        raise

    logger.info(
        "Knowledge document uploaded: knowledge_base_id=%s document_id=%s size=%s",
        knowledge_base_id,
        document.id,
        document.size_bytes,
    )
    return document


def delete_document(knowledge_base_id, document_id, storage=None):
    storage = _storage(storage)
    try:
        with transaction.atomic():
            document = KnowledgeDocument.objects.select_for_update().get(
                pk=document_id,
                knowledge_base_id=knowledge_base_id,
            )
            document.status = KnowledgeDocument.Status.DELETING
            document.error_message = ""
            document.save(update_fields=("status", "error_message", "updated_at"))
            storage_key = document.storage_key
    except KnowledgeDocument.DoesNotExist as exc:
        raise NotFound("文件不存在。") from exc

    try:
        storage.delete(storage_key)
    except StorageError as exc:
        _save_delete_error(document_id, "原文删除失败，可重试。")
        logger.error(
            "Knowledge document file deletion failed: knowledge_base_id=%s document_id=%s error=%s",
            knowledge_base_id,
            document_id,
            type(exc).__name__,
        )
        raise APIException("原文删除失败，可重试。") from exc

    try:
        with transaction.atomic():
            document = KnowledgeDocument.objects.select_for_update().get(
                pk=document_id,
                knowledge_base_id=knowledge_base_id,
            )
            document.delete()
    except KnowledgeDocument.DoesNotExist:
        return
    except DatabaseError as exc:
        _save_delete_error(document_id, "文件记录删除失败，可重试。")
        logger.error(
            "Knowledge document record deletion failed: knowledge_base_id=%s document_id=%s error=%s",
            knowledge_base_id,
            document_id,
            type(exc).__name__,
        )
        raise APIException("文件记录删除失败，可重试。") from exc

    logger.info(
        "Knowledge document deleted: knowledge_base_id=%s document_id=%s",
        knowledge_base_id,
        document_id,
    )


def _cleanup_unregistered_file(storage, stored_file, knowledge_base_id):
    try:
        storage.delete(stored_file.storage_key)
    except StorageError as exc:
        logger.error(
            "Unregistered knowledge file cleanup failed: knowledge_base_id=%s error=%s",
            knowledge_base_id,
            type(exc).__name__,
        )


def _save_delete_error(document_id, message):
    try:
        KnowledgeDocument.objects.filter(pk=document_id).update(
            status=KnowledgeDocument.Status.DELETING,
            error_message=message,
        )
    except DatabaseError:
        logger.error(
            "Knowledge document deletion error could not be saved: document_id=%s",
            document_id,
        )
