import hashlib

from django.db import IntegrityError, transaction
from django.db.models.deletion import RestrictedError
from django.test import TestCase

from knowledge.models import KnowledgeBase, KnowledgeDocument


class KnowledgeModelTests(TestCase):
    def setUp(self):
        self.knowledge_base = KnowledgeBase.objects.create(
            name="运维制度",
            description="内部运维规范",
        )
        self.other_base = KnowledgeBase.objects.create(
            name="值班手册",
            description="值班流程",
        )

    def create_document(self, knowledge_base=None, content=b"content", **kwargs):
        values = {
            "knowledge_base": knowledge_base or self.knowledge_base,
            "original_name": "guide.md",
            "storage_key": f"{(knowledge_base or self.knowledge_base).id}/file.md",
            "mime_type": "text/markdown",
            "extension": ".md",
            "size_bytes": len(content),
            "content_hash": hashlib.sha256(content).hexdigest(),
        }
        values.update(kwargs)
        return KnowledgeDocument.objects.create(**values)

    def test_tables_constraints_and_ordering(self):
        self.assertEqual(KnowledgeBase._meta.db_table, "knowledge_bases")
        self.assertEqual(KnowledgeDocument._meta.db_table, "knowledge_documents")
        self.assertEqual(
            KnowledgeBase._meta.ordering,
            ("-updated_at", "-id"),
        )
        self.assertEqual(
            KnowledgeDocument._meta.ordering,
            ("-created_at", "-id"),
        )

    def test_knowledge_base_name_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            KnowledgeBase.objects.create(name="运维制度", description="重复")

    def test_hash_is_unique_per_base_but_reusable_across_bases(self):
        self.create_document()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_document(storage_key=f"{self.knowledge_base.id}/duplicate.md")

        other = self.create_document(
            knowledge_base=self.other_base,
            storage_key=f"{self.other_base.id}/same.md",
        )
        self.assertEqual(other.knowledge_base, self.other_base)

    def test_document_check_constraints(self):
        invalid_values = (
            {"size_bytes": 0},
            {"ingestion_version": 0},
            {"status": "unknown"},
        )
        for index, values in enumerate(invalid_values):
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.create_document(
                        content=f"content-{index}".encode(),
                        storage_key=f"{self.knowledge_base.id}/invalid-{index}.md",
                        **values,
                    )

    def test_document_foreign_key_restricts_base_deletion(self):
        self.create_document()
        with self.assertRaises(RestrictedError):
            self.knowledge_base.delete()
