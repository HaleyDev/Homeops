from django.conf import settings
from django.db import models
from django.db.models import Q
from pgvector.django import VectorField

from system_setting.models import EMBEDDING_DIMENSIONS, LLMModel


class KnowledgeBase(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=300)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_knowledge_bases",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_bases"
        ordering = ("-updated_at", "-id")
        verbose_name = "知识库"
        verbose_name_plural = "知识库"

    def __str__(self):
        return self.name


class KnowledgeDocument(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "已上传"
        PROCESSING = "processing", "向量化中"
        READY = "ready", "已向量化"
        FAILED = "failed", "处理失败"
        DELETING = "deleting", "删除中"

    knowledge_base = models.ForeignKey(
        KnowledgeBase,
        on_delete=models.RESTRICT,
        related_name="documents",
    )
    original_name = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=512, unique=True)
    mime_type = models.CharField(max_length=64)
    extension = models.CharField(max_length=8)
    size_bytes = models.PositiveBigIntegerField()
    content_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.UPLOADED,
    )
    error_message = models.TextField(blank=True, default="")
    ingestion_version = models.PositiveIntegerField(default=1)
    ingestion_task_id = models.CharField(max_length=100, blank=True, default="")
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    embedding_profile_hash = models.CharField(max_length=64, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_knowledge_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_documents"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("knowledge_base", "content_hash"),
                name="uniq_knowledge_document_hash",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gt=0),
                name="knowledge_document_size_positive",
            ),
            models.CheckConstraint(
                condition=Q(ingestion_version__gt=0),
                name="knowledge_document_version_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=("uploaded", "processing", "ready", "failed", "deleting")
                ),
                name="knowledge_document_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("knowledge_base", "-created_at", "-id"),
                name="knowledge_doc_kb_created_idx",
            ),
            models.Index(
                fields=("status", "updated_at"),
                name="knowledge_doc_status_idx",
            ),
        ]
        verbose_name = "知识库文档"
        verbose_name_plural = "知识库文档"

    def __str__(self):
        return self.original_name


class KnowledgeDocumentChunk(models.Model):
    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    source_meta = models.JSONField(default=dict, blank=True)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)
    embedding_model = models.ForeignKey(
        LLMModel,
        on_delete=models.PROTECT,
        related_name="knowledge_chunks",
    )
    embedding_provider_id = models.BigIntegerField()
    embedding_model_key = models.CharField(max_length=160)
    embedding_dimensions = models.PositiveIntegerField()
    embedding_profile_hash = models.CharField(max_length=64)
    ingestion_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "knowledge_document_chunks"
        ordering = ("document_id", "chunk_index")
        constraints = [
            models.UniqueConstraint(
                fields=("document", "chunk_index"),
                name="uniq_knowledge_chunk_position",
            ),
            models.CheckConstraint(
                condition=Q(chunk_index__gte=0),
                name="knowledge_chunk_index_valid",
            ),
            models.CheckConstraint(
                condition=Q(ingestion_version__gt=0),
                name="knowledge_chunk_version_valid",
            ),
            models.CheckConstraint(
                condition=Q(embedding_dimensions=EMBEDDING_DIMENSIONS),
                name="knowledge_chunk_dims_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("document", "ingestion_version"),
                name="knowledge_chunk_doc_ver_idx",
            ),
            models.Index(
                fields=("embedding_model", "embedding_profile_hash", "document"),
                name="knowledge_chunk_model_idx",
            ),
        ]
        verbose_name = "知识库文档分块"
        verbose_name_plural = "知识库文档分块"

    def __str__(self):
        return f"{self.document_id}:{self.chunk_index}"
