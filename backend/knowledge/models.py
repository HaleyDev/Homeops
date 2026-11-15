from django.conf import settings
from django.db import models
from django.db.models import Q


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
