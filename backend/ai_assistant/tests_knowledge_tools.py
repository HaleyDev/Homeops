import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from knowledge.embeddings import EmbeddingUnavailableError
from knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentChunk
from system_setting.models import LLMModel, LLMProvider, ModelType
from system_setting.services import EffectiveModelConfig, ModelConfigurationError

from .agent.tools.knowledge import (
    _knowledge_search,
    _list_knowledge_bases,
    knowledge_search,
    list_knowledge_bases,
)


def vector(first=1.0, second=0.0):
    return [first, second] + [0.0] * 2046


class KnowledgeToolDatabaseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reader",
            password="password",
        )
        self.knowledge_base = KnowledgeBase.objects.create(
            name="运维手册",
            description="数据库和服务器运维资料",
        )
        self.other_base = KnowledgeBase.objects.create(
            name="其他资料",
            description="不应串库的内容",
        )
        self.empty_base = KnowledgeBase.objects.create(
            name="空知识库",
            description="暂时没有文档",
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
        self.other_model = LLMModel.objects.create(
            provider=self.provider,
            model_key="old-embedding-model",
            display_name="Old Embedding",
            model_type=ModelType.EMBEDDING,
            dimensions=2048,
        )
        self.config = EffectiveModelConfig(
            model_id=self.model.id,
            provider_id=self.provider.id,
            model_key=self.model.model_key,
            model_type=ModelType.EMBEDDING,
            protocol="openai_compatible",
            base_url=self.provider.base_url,
            dimensions=2048,
            api_key="secret",
        )
        self.document = self.create_document(self.knowledge_base, "current.txt")
        self.processing_document = self.create_document(
            self.knowledge_base,
            "processing.txt",
            status=KnowledgeDocument.Status.PROCESSING,
            ingestion_version=1,
        )
        self.other_document = self.create_document(
            self.other_base,
            "other.txt",
            ingestion_version=1,
        )
        self.profile_hash = "current-profile"
        self.get_config = patch(
            "ai_assistant.agent.tools.knowledge.get_effective_model_config"
        ).start()
        self.get_config.return_value = self.config
        embedder_class = patch(
            "ai_assistant.agent.tools.knowledge.OpenAICompatibleEmbedder"
        ).start()
        self.addCleanup(patch.stopall)
        self.embedder = embedder_class.return_value.__enter__.return_value
        self.embedder.embed.return_value = [vector()]
        self.embedder.profile_hash = self.profile_hash

    def create_document(
        self,
        knowledge_base,
        name,
        *,
        status=KnowledgeDocument.Status.READY,
        ingestion_version=2,
    ):
        return KnowledgeDocument.objects.create(
            knowledge_base=knowledge_base,
            original_name=name,
            storage_key=f"test/{name}",
            mime_type="text/plain",
            extension=".txt",
            size_bytes=10,
            content_hash=hashlib.sha256(name.encode()).hexdigest(),
            status=status,
            ingestion_version=ingestion_version,
        )

    def create_chunk(self, document, index, content, embedding=None, **overrides):
        values = {
            "document": document,
            "chunk_index": index,
            "content": content,
            "source_meta": {"char_start": index * 10, "char_end": index * 10 + 8},
            "embedding": embedding or vector(),
            "embedding_model": self.model,
            "embedding_provider_id": self.provider.id,
            "embedding_model_key": self.model.model_key,
            "embedding_dimensions": 2048,
            "embedding_profile_hash": self.profile_hash,
            "ingestion_version": document.ingestion_version,
        }
        values.update(overrides)
        return KnowledgeDocumentChunk.objects.create(**values)

    def test_list_knowledge_bases_returns_names_descriptions_and_ready_counts(self):
        self.create_chunk(self.document, 0, "ready")

        result = _list_knowledge_bases(self.user.id)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total"], 3)
        items = {item["name"]: item for item in result["items"]}
        self.assertEqual(items["运维手册"]["ready_document_count"], 1)
        self.assertEqual(items["运维手册"]["description"], "数据库和服务器运维资料")
        self.assertEqual(items["其他资料"]["ready_document_count"], 1)
        self.assertEqual(items["空知识库"]["ready_document_count"], 0)

    def test_search_filters_scope_version_status_and_model_then_orders_by_distance(self):
        nearest = self.create_chunk(self.document, 0, "current-nearest")
        second = self.create_chunk(
            self.document,
            1,
            "current-second",
            embedding=vector(0.9, 0.1),
        )
        self.create_chunk(
            self.document,
            2,
            "old-version",
            ingestion_version=1,
        )
        self.create_chunk(
            self.document,
            3,
            "old-profile",
            embedding_profile_hash="old-profile",
        )
        self.create_chunk(
            self.document,
            4,
            "old-model",
            embedding_model=self.other_model,
            embedding_model_key=self.other_model.model_key,
        )
        self.create_chunk(self.processing_document, 0, "processing")
        self.create_chunk(self.other_document, 0, "other-base")

        result = _knowledge_search(
            self.user.id,
            self.knowledge_base.id,
            "  数据库备份  ",
            2,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            [item["document_id"] for item in result["items"]],
            [self.document.id, self.document.id],
        )
        self.assertEqual(
            [item["content"] for item in result["items"]],
            [nearest.content, second.content],
        )
        self.assertEqual(result["items"][0]["document_name"], "current.txt")
        self.assertEqual(result["items"][0]["source_meta"]["char_start"], 0)
        self.assertAlmostEqual(result["items"][0]["score"], 1.0)
        self.embedder.embed.assert_called_once_with(["数据库备份"])
        self.get_config.assert_called_once_with(ModelType.EMBEDDING)

        limited = _knowledge_search(
            self.user.id,
            self.knowledge_base.id,
            "数据库备份",
            1,
        )
        self.assertEqual(limited["total"], 1)
        self.assertEqual(limited["items"][0]["content"], "current-nearest")

    def test_search_returns_empty_items_when_current_model_has_no_compatible_vectors(self):
        self.create_chunk(self.document, 0, "old-profile")
        self.embedder.profile_hash = "new-profile"

        result = _knowledge_search(
            self.user.id,
            self.knowledge_base.id,
            "没有结果",
            5,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)

    def test_search_validates_ids_query_and_top_k(self):
        cases = [
            (0, "query", 5),
            (True, "query", 5),
            (self.knowledge_base.id, " ", 5),
            (self.knowledge_base.id, "x" * 1001, 5),
            (self.knowledge_base.id, "query", 0),
            (self.knowledge_base.id, "query", 11),
            (self.knowledge_base.id, "query", True),
        ]
        for knowledge_base_id, query, top_k in cases:
            with self.subTest(
                knowledge_base_id=knowledge_base_id,
                query_length=len(query),
                top_k=top_k,
            ):
                result = _knowledge_search(
                    self.user.id,
                    knowledge_base_id,
                    query,
                    top_k,
                )
                self.assertEqual(result["status"], "error")
        self.embedder.embed.assert_not_called()

    def test_search_rejects_unknown_user_and_knowledge_base(self):
        missing_user = _list_knowledge_bases(self.user.id + 1000)
        missing_base = _knowledge_search(
            self.user.id,
            self.knowledge_base.id + 1000,
            "query",
            5,
        )

        self.assertEqual(missing_user["status"], "error")
        self.assertEqual(missing_base["status"], "error")
        self.embedder.embed.assert_not_called()

    def test_search_returns_safe_model_and_embedding_errors(self):
        self.get_config.side_effect = ModelConfigurationError("secret details")
        config_error = _knowledge_search(
            self.user.id,
            self.knowledge_base.id,
            "query",
            5,
        )
        self.assertEqual(config_error["status"], "error")
        self.assertNotIn("secret details", config_error["error_message"])

        self.get_config.side_effect = None
        self.embedder.embed.side_effect = EmbeddingUnavailableError()
        embedding_error = _knowledge_search(
            self.user.id,
            self.knowledge_base.id,
            "query",
            5,
        )
        self.assertEqual(embedding_error["status"], "error")
        self.assertEqual(
            embedding_error["error_message"],
            EmbeddingUnavailableError.safe_message,
        )


class KnowledgeToolContextTests(SimpleTestCase):
    def test_public_tools_reject_missing_user_context(self):
        context = SimpleNamespace(user_id="")

        list_result = async_to_sync(list_knowledge_bases)(context)
        search_result = async_to_sync(knowledge_search)(1, "query", context)

        self.assertEqual(list_result["status"], "error")
        self.assertEqual(search_result["status"], "error")
