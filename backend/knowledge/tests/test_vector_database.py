import hashlib

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from pgvector.django import CosineDistance
from rest_framework.test import APIClient

from knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentChunk
from system_setting.models import LLMModel, LLMProvider, ModelType


def vector(first=1.0, second=0.0):
    return [first, second] + [0.0] * 2046


class VectorDatabaseTests(TestCase):
    def setUp(self):
        self.knowledge_base = KnowledgeBase.objects.create(
            name="向量测试", description="PostgreSQL pgvector"
        )
        self.document = KnowledgeDocument.objects.create(
            knowledge_base=self.knowledge_base,
            original_name="document.txt",
            storage_key="1/vector.txt",
            mime_type="text/plain",
            extension=".txt",
            size_bytes=7,
            content_hash=hashlib.sha256(b"content").hexdigest(),
        )
        self.provider = LLMProvider.objects.create(
            name="embedding",
            slug="embedding",
            base_url="https://embedding.example.com/v1",
            api_key_ciphertext="encrypted",
        )
        self.model = LLMModel.objects.create(
            provider=self.provider,
            model_key="embedding-model",
            display_name="Embedding",
            model_type=ModelType.EMBEDDING,
            dimensions=2048,
        )

    def create_chunk(self, document=None, index=0, embedding=None, **overrides):
        document = document or self.document
        values = {
            "document": document,
            "chunk_index": index,
            "content": f"chunk-{index}",
            "embedding": embedding or vector(),
            "embedding_model": self.model,
            "embedding_provider_id": self.provider.id,
            "embedding_model_key": self.model.model_key,
            "embedding_dimensions": 2048,
            "embedding_profile_hash": "profile",
            "ingestion_version": 1,
        }
        values.update(overrides)
        return KnowledgeDocumentChunk.objects.create(**values)

    def test_extension_column_and_only_btree_indexes_exist(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            self.assertIsNotNone(cursor.fetchone())
            cursor.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'knowledge_document_chunks'::regclass "
                "AND attname = 'embedding'"
            )
            self.assertEqual(cursor.fetchone()[0], "vector(2048)")
            cursor.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'knowledge_document_chunks'"
            )
            indexes = dict(cursor.fetchall())
        self.assertIn("knowledge_chunk_doc_ver_idx", indexes)
        self.assertIn("knowledge_chunk_model_idx", indexes)
        self.assertFalse(any("USING hnsw" in value for value in indexes.values()))

    def test_exact_cosine_distance_orders_correctly(self):
        first = self.create_chunk(index=0, embedding=vector(1, 0))
        second = self.create_chunk(index=1, embedding=vector(0, 1))
        ordered = list(
            KnowledgeDocumentChunk.objects.annotate(
                distance=CosineDistance("embedding", vector(1, 0))
            ).order_by("distance")
        )
        self.assertEqual([chunk.id for chunk in ordered], [first.id, second.id])
        self.assertAlmostEqual(ordered[0].distance, 0)
        self.assertAlmostEqual(ordered[1].distance, 1)

    def test_vector_dimension_and_chunk_position_constraints(self):
        self.create_chunk()
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.create_chunk(index=0)
        with self.assertRaises(DatabaseError), transaction.atomic():
            self.create_chunk(index=1, embedding=[1.0, 2.0])

    def test_document_cascade_and_model_delete_protection(self):
        self.create_chunk()
        admin = get_user_model().objects.create_superuser(
            username="admin", password="password"
        )
        client = APIClient()
        client.force_authenticate(admin)
        response = client.delete(f"/api/system-setting/llm/models/{self.model.id}/")
        self.assertEqual(response.status_code, 409)
        response = client.delete(
            f"/api/system-setting/llm/providers/{self.provider.id}/"
        )
        self.assertEqual(response.status_code, 409)

        self.document.delete()
        self.assertEqual(KnowledgeDocumentChunk.objects.count(), 0)
