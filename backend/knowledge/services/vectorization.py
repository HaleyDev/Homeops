import logging
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import DatabaseError, transaction
from django.utils import timezone

from knowledge.chunking import (
    ChunkingError,
    ChunkLimitError,
    EmptyDocumentError,
    split_text,
)
from knowledge.embeddings import EmbeddingError, OpenAICompatibleEmbedder
from knowledge.models import KnowledgeDocument, KnowledgeDocumentChunk
from knowledge.storage import KnowledgeFileStorage, StorageError
from system_setting.models import ModelType
from system_setting.services import (
    ModelConfigurationError,
    get_effective_model_config,
)

logger = logging.getLogger(__name__)

DISPATCH_ERROR = "向量化任务投递失败，请重试。"
INTERRUPTED_ERROR = "向量化任务执行中断，请手动重试。"


class DocumentStateChanged(Exception):
    pass


def claim_document(document_id, ingestion_version, task_id):
    now = timezone.now()
    claimed = KnowledgeDocument.objects.filter(
        pk=document_id,
        ingestion_version=ingestion_version,
        status=KnowledgeDocument.Status.UPLOADED,
    ).update(
        status=KnowledgeDocument.Status.PROCESSING,
        ingestion_task_id=task_id,
        processing_started_at=now,
        processed_at=None,
        error_message="",
        updated_at=now,
    )
    if claimed != 1:
        return None
    return KnowledgeDocument.objects.get(pk=document_id)


def process_document(
    document_id,
    ingestion_version,
    task_id,
    *,
    storage=None,
    embedder_factory=OpenAICompatibleEmbedder,
):
    document = claim_document(document_id, ingestion_version, task_id)
    if document is None:
        return False

    try:
        config = get_effective_model_config(ModelType.EMBEDDING)
        storage = storage or KnowledgeFileStorage()
        text = storage.read_text(document.storage_key)
        chunks = split_text(
            text,
            chunk_size=settings.KNOWLEDGE_CHUNK_SIZE,
            overlap=settings.KNOWLEDGE_CHUNK_OVERLAP,
            max_chunks=settings.KNOWLEDGE_MAX_CHUNKS_PER_DOCUMENT,
        )
        if not chunks:
            raise EmptyDocumentError()

        chunk_models = []
        with embedder_factory(config) as embedder:
            for batch_start in range(
                0, len(chunks), settings.KNOWLEDGE_EMBEDDING_BATCH_SIZE
            ):
                batch = chunks[
                    batch_start : batch_start
                    + settings.KNOWLEDGE_EMBEDDING_BATCH_SIZE
                ]
                vectors = embedder.embed([chunk.content for chunk in batch])
                for chunk, vector in zip(batch, vectors, strict=True):
                    chunk_models.append(
                        KnowledgeDocumentChunk(
                            document=document,
                            chunk_index=len(chunk_models),
                            content=chunk.content,
                            source_meta=chunk.source_meta,
                            embedding=vector,
                            embedding_model_id=config.model_id,
                            embedding_provider_id=config.provider_id,
                            embedding_model_key=config.model_key,
                            embedding_dimensions=config.dimensions,
                            embedding_profile_hash=embedder.profile_hash,
                            ingestion_version=ingestion_version,
                        )
                    )
            profile_hash = embedder.profile_hash

        with transaction.atomic():
            current = KnowledgeDocument.objects.select_for_update().get(
                pk=document_id
            )
            if (
                current.ingestion_version != ingestion_version
                or current.status != KnowledgeDocument.Status.PROCESSING
            ):
                raise DocumentStateChanged()
            current.chunks.all().delete()
            KnowledgeDocumentChunk.objects.bulk_create(chunk_models, batch_size=100)
            current.status = KnowledgeDocument.Status.READY
            current.error_message = ""
            current.processed_at = timezone.now()
            current.embedding_profile_hash = profile_hash
            current.save(
                update_fields=(
                    "status",
                    "error_message",
                    "processed_at",
                    "embedding_profile_hash",
                    "updated_at",
                )
            )
        logger.info(
            "Knowledge document vectorized: document_id=%s version=%s chunks=%s",
            document_id,
            ingestion_version,
            len(chunk_models),
        )
        return True
    except DocumentStateChanged:
        logger.info(
            "Knowledge document vectorization discarded after state change: "
            "document_id=%s version=%s",
            document_id,
            ingestion_version,
        )
        return False
    except KnowledgeDocument.DoesNotExist:
        return False
    except Exception as exc:
        mark_failed(document_id, ingestion_version, _safe_error_message(exc))
        logger.error(
            "Knowledge document vectorization failed: document_id=%s version=%s "
            "task_id=%s error=%s",
            document_id,
            ingestion_version,
            task_id,
            type(exc).__name__,
        )
        return False


def mark_failed(document_id, ingestion_version, message):
    now = timezone.now()
    try:
        KnowledgeDocument.objects.filter(
            pk=document_id,
            ingestion_version=ingestion_version,
            status=KnowledgeDocument.Status.PROCESSING,
        ).update(
            status=KnowledgeDocument.Status.FAILED,
            error_message=message[:1000],
            processed_at=now,
            updated_at=now,
        )
    except DatabaseError:
        logger.error(
            "Knowledge document failure state could not be saved: document_id=%s "
            "version=%s",
            document_id,
            ingestion_version,
        )


def recover_stale_documents(now=None):
    now = now or timezone.now()
    uploaded_before = now - timedelta(
        seconds=settings.KNOWLEDGE_UPLOADED_STALE_SECONDS
    )
    processing_before = now - timedelta(
        seconds=settings.KNOWLEDGE_PROCESSING_STALE_SECONDS
    )

    processing_failed = 0
    stale_processing = KnowledgeDocument.objects.filter(
        status=KnowledgeDocument.Status.PROCESSING,
        processing_started_at__lte=processing_before,
    ).values("id", "ingestion_version", "processing_started_at")
    for document in list(stale_processing):
        processing_failed += KnowledgeDocument.objects.filter(
            pk=document["id"],
            ingestion_version=document["ingestion_version"],
            status=KnowledgeDocument.Status.PROCESSING,
            processing_started_at=document["processing_started_at"],
        ).update(
            status=KnowledgeDocument.Status.FAILED,
            error_message=INTERRUPTED_ERROR,
            processed_at=now,
            updated_at=now,
        )

    from knowledge.tasks import dispatch_vectorization

    stale_uploaded = KnowledgeDocument.objects.filter(
        status=KnowledgeDocument.Status.UPLOADED,
        updated_at__lte=uploaded_before,
    ).values("id", "ingestion_version")
    redispatched = 0
    for document in list(stale_uploaded):
        redispatched += int(
            dispatch_vectorization(document["id"], document["ingestion_version"])
        )
    return {"processing_failed": processing_failed, "redispatched": redispatched}


def _safe_error_message(exc):
    if isinstance(exc, ModelConfigurationError):
        return "向量模型未配置或不可用，请联系管理员检查系统设置。"
    if isinstance(exc, StorageError):
        return "原始文件不存在或无法读取，请重新上传或联系管理员。"
    if isinstance(exc, EmptyDocumentError):
        return "文档没有可向量化的文本内容。"
    if isinstance(exc, ChunkLimitError):
        return "文档分块数量超过当前上限，请拆分文件后重试。"
    if isinstance(exc, ChunkingError):
        return "文档分块配置无效，请联系管理员检查系统设置。"
    if isinstance(exc, EmbeddingError):
        return exc.safe_message
    if isinstance(exc, SoftTimeLimitExceeded):
        return INTERRUPTED_ERROR
    if isinstance(exc, DatabaseError):
        return "向量数据保存失败，请重试；详细原因已记录到服务端日志。"
    return "向量化任务执行失败，请手动重试。"
