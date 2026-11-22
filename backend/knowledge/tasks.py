import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import KnowledgeDocument
from .services.vectorization import (
    DISPATCH_ERROR,
    process_document,
    recover_stale_documents,
)

logger = logging.getLogger(__name__)


def vectorization_task_id(document_id, ingestion_version):
    return f"knowledge.document.vectorize:{document_id}:{ingestion_version}"


def dispatch_vectorization(document_id, ingestion_version):
    try:
        vectorize_document.apply_async(
            kwargs={
                "document_id": document_id,
                "ingestion_version": ingestion_version,
            },
            task_id=vectorization_task_id(document_id, ingestion_version),
            queue="knowledge",
        )
        return True
    except Exception as exc:
        now = timezone.now()
        KnowledgeDocument.objects.filter(
            pk=document_id,
            ingestion_version=ingestion_version,
            status=KnowledgeDocument.Status.UPLOADED,
        ).update(
            status=KnowledgeDocument.Status.FAILED,
            error_message=DISPATCH_ERROR,
            processed_at=now,
            updated_at=now,
        )
        logger.error(
            "Knowledge document task dispatch failed: document_id=%s version=%s "
            "error=%s",
            document_id,
            ingestion_version,
            type(exc).__name__,
        )
        return False


@shared_task(
    bind=True,
    name="knowledge.document.vectorize",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=settings.KNOWLEDGE_TASK_SOFT_TIME_LIMIT,
    time_limit=settings.KNOWLEDGE_TASK_TIME_LIMIT,
)
def vectorize_document(self, document_id, ingestion_version):
    return process_document(document_id, ingestion_version, self.request.id)


@shared_task(name="knowledge.document.recover_stale")
def recover_stale_knowledge_documents():
    return recover_stale_documents()
