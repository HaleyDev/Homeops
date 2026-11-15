import hashlib
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone

from knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentChunk
from knowledge.services.vectorization import process_document, recover_stale_documents
from knowledge.storage import KnowledgeFileStorage
from system_setting.crypto import encrypt_api_key
from system_setting.models import LLMModel, LLMProvider, ModelType
from system_setting.services import clear_selection, select_model


def vector(value=1.0):
    return [value] + [0.0] * 2047


class FakeEmbedder:
    instances = []

    def __init__(self, config):
        self.config = config
        self.profile_hash = "fake-profile"
        self.calls = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def embed(self, texts):
        self.calls.append(texts)
        return [vector(index + 1) for index, _text in enumerate(texts)]


class VectorizationTests(TestCase):
    def setUp(self):
        FakeEmbedder.instances = []
        key_patch = patch.dict(
            os.environ,
            {
                "SYSTEM_SETTING_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SYSTEM_SETTING_ENCRYPTION_KEY_VERSION": "test",
            },
        )
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.storage = KnowledgeFileStorage(root=self.temporary_directory.name)
        self.knowledge_base = KnowledgeBase.objects.create(
            name="运维制度", description="内部规范"
        )
        ciphertext, version = encrypt_api_key("test-secret")
        self.provider = LLMProvider.objects.create(
            name="embedding",
            slug="embedding",
            base_url="https://embedding.example.com/v1",
            api_key_ciphertext=ciphertext,
            api_key_version=version,
        )
        self.model = LLMModel.objects.create(
            provider=self.provider,
            model_key="embedding-model",
            display_name="Embedding",
            model_type=ModelType.EMBEDDING,
            dimensions=2048,
        )
        select_model(ModelType.EMBEDDING, self.model.id)
        self.document_counter = 0

    def create_document(self, text="需要向量化的中文内容🙂", **overrides):
        self.document_counter += 1
        storage_key = f"{self.knowledge_base.id}/document-{self.document_counter}.txt"
        path = Path(self.temporary_directory.name) / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        content = text.encode("utf-8")
        values = {
            "knowledge_base": self.knowledge_base,
            "original_name": f"document-{self.document_counter}.txt",
            "storage_key": storage_key,
            "mime_type": "text/plain",
            "extension": ".txt",
            "size_bytes": len(content),
            "content_hash": hashlib.sha256(content).hexdigest(),
        }
        values.update(overrides)
        return KnowledgeDocument.objects.create(**values)

    def process(self, document, version=1, factory=FakeEmbedder):
        return process_document(
            document.id,
            version,
            "test-task",
            storage=self.storage,
            embedder_factory=factory,
        )

    @override_settings(
        KNOWLEDGE_CHUNK_SIZE=5,
        KNOWLEDGE_CHUNK_OVERLAP=1,
        KNOWLEDGE_EMBEDDING_BATCH_SIZE=2,
    )
    def test_ready_flow_batches_and_snapshots_model_identity(self):
        document = self.create_document("abcdefghijklmnop")
        self.assertTrue(self.process(document))
        document.refresh_from_db()
        self.assertEqual(document.status, KnowledgeDocument.Status.READY)
        self.assertEqual(document.ingestion_task_id, "test-task")
        self.assertEqual(document.embedding_profile_hash, "fake-profile")
        self.assertIsNotNone(document.processing_started_at)
        self.assertIsNotNone(document.processed_at)
        self.assertEqual(document.error_message, "")
        chunks = list(document.chunks.order_by("chunk_index"))
        self.assertGreater(len(chunks), 2)
        self.assertGreater(len(FakeEmbedder.instances[0].calls), 1)
        for index, chunk in enumerate(chunks):
            self.assertEqual(chunk.chunk_index, index)
            self.assertEqual(chunk.embedding_model_id, self.model.id)
            self.assertEqual(chunk.embedding_provider_id, self.provider.id)
            self.assertEqual(chunk.embedding_model_key, self.model.model_key)
            self.assertEqual(chunk.embedding_dimensions, 2048)
            self.assertEqual(chunk.ingestion_version, 1)
            self.assertIn("char_start", chunk.source_meta)

    def test_duplicate_and_stale_messages_do_not_call_embedding(self):
        document = self.create_document()
        self.assertTrue(self.process(document))
        instance_count = len(FakeEmbedder.instances)
        chunk_count = document.chunks.count()
        self.assertFalse(self.process(document))
        self.assertEqual(len(FakeEmbedder.instances), instance_count)
        self.assertEqual(document.chunks.count(), chunk_count)

        other = self.create_document("other", ingestion_version=2)
        self.assertFalse(self.process(other, version=1))
        other.refresh_from_db()
        self.assertEqual(other.status, KnowledgeDocument.Status.UPLOADED)
        self.assertEqual(len(FakeEmbedder.instances), instance_count)

    def test_missing_model_blank_and_missing_file_enter_failed_safely(self):
        clear_selection(ModelType.EMBEDDING)
        missing_model = self.create_document("missing-model")
        self.assertFalse(self.process(missing_model))
        missing_model.refresh_from_db()
        self.assertEqual(missing_model.status, KnowledgeDocument.Status.FAILED)
        self.assertIn("向量模型未配置", missing_model.error_message)
        self.assertNotIn("test-secret", missing_model.error_message)

        select_model(ModelType.EMBEDDING, self.model.id)
        blank = self.create_document("   \n ")
        self.assertFalse(self.process(blank))
        blank.refresh_from_db()
        self.assertEqual(blank.error_message, "文档没有可向量化的文本内容。")

        missing_file = self.create_document("missing")
        (Path(self.temporary_directory.name) / missing_file.storage_key).unlink()
        self.assertFalse(self.process(missing_file))
        missing_file.refresh_from_db()
        self.assertIn("原始文件不存在或无法读取", missing_file.error_message)
        self.assertNotIn(self.temporary_directory.name, missing_file.error_message)

    def test_old_worker_cannot_overwrite_new_version(self):
        document = self.create_document()

        class StateChangingEmbedder(FakeEmbedder):
            def embed(self, texts):
                KnowledgeDocument.objects.filter(pk=document.id).update(
                    ingestion_version=2,
                    status=KnowledgeDocument.Status.FAILED,
                    error_message="new version failure",
                )
                return super().embed(texts)

        self.assertFalse(self.process(document, factory=StateChangingEmbedder))
        document.refresh_from_db()
        self.assertEqual(document.ingestion_version, 2)
        self.assertEqual(document.status, KnowledgeDocument.Status.FAILED)
        self.assertEqual(document.error_message, "new version failure")
        self.assertEqual(document.chunks.count(), 0)

    def test_final_transaction_rolls_back_chunk_replacement(self):
        document = self.create_document()
        old_chunk = KnowledgeDocumentChunk.objects.create(
            document=document,
            chunk_index=0,
            content="old",
            embedding=vector(),
            embedding_model=self.model,
            embedding_provider_id=self.provider.id,
            embedding_model_key=self.model.model_key,
            embedding_dimensions=2048,
            embedding_profile_hash="old-profile",
            ingestion_version=1,
        )
        with patch(
            "knowledge.services.vectorization.KnowledgeDocumentChunk.objects.bulk_create",
            side_effect=DatabaseError("database unavailable"),
        ):
            self.assertFalse(self.process(document))
        document.refresh_from_db()
        self.assertEqual(document.status, KnowledgeDocument.Status.FAILED)
        self.assertIn("向量数据保存失败", document.error_message)
        self.assertEqual(document.chunks.count(), 1)
        self.assertEqual(document.chunks.get().id, old_chunk.id)
        self.assertEqual(document.chunks.get().content, "old")

    def test_stale_recovery_redispatches_uploaded_and_fails_processing(self):
        now = timezone.now()
        uploaded = self.create_document("uploaded")
        processing = self.create_document(
            "processing",
            status=KnowledgeDocument.Status.PROCESSING,
            ingestion_version=3,
        )
        recent = self.create_document(
            "recent",
            status=KnowledgeDocument.Status.PROCESSING,
        )
        KnowledgeDocument.objects.filter(pk=uploaded.id).update(
            updated_at=now - timedelta(minutes=6)
        )
        KnowledgeDocument.objects.filter(pk=processing.id).update(
            processing_started_at=now - timedelta(minutes=40)
        )
        KnowledgeDocument.objects.filter(pk=recent.id).update(
            processing_started_at=now
        )
        with patch(
            "knowledge.tasks.dispatch_vectorization", return_value=True
        ) as dispatch:
            result = recover_stale_documents(now=now)
        self.assertEqual(result, {"processing_failed": 1, "redispatched": 1})
        dispatch.assert_called_once_with(uploaded.id, 1)
        processing.refresh_from_db()
        recent.refresh_from_db()
        self.assertEqual(processing.status, KnowledgeDocument.Status.FAILED)
        self.assertEqual(processing.error_message, "向量化任务执行中断，请手动重试。")
        self.assertEqual(recent.status, KnowledgeDocument.Status.PROCESSING)
