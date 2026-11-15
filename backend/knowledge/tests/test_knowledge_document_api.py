import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, IntegrityError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from knowledge.models import KnowledgeBase, KnowledgeDocument
from knowledge.storage import StorageError


class KnowledgeDocumentApiTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.settings_override = override_settings(
            KNOWLEDGE_UPLOAD_ROOT=self.temporary_directory.name,
            KNOWLEDGE_MAX_FILE_SIZE=20 * 1024 * 1024,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.root = Path(self.temporary_directory.name)
        self.admin = get_user_model().objects.create_superuser(
            username="admin",
            password="password",
        )
        self.user = get_user_model().objects.create_user(
            username="user",
            password="password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.knowledge_base = KnowledgeBase.objects.create(
            name="运维制度",
            description="内部规范",
        )
        self.other_base = KnowledgeBase.objects.create(
            name="其他制度",
            description="其他规范",
        )
        self.url = f"/api/knowledge-bases/{self.knowledge_base.id}/documents/"

    def upload(self, name="值班规范.md", content="# 值班内容".encode(), url=None):
        return self.client.post(
            url or self.url,
            {"file": SimpleUploadedFile(name, content)},
            format="multipart",
        )

    def stored_files(self):
        return [path for path in self.root.rglob("*") if path.is_file()]

    def test_upload_markdown_and_txt_persists_real_file(self):
        for name, content in (("值班规范.md", "# 值班内容".encode()), ("notes.txt", b"notes")):
            with self.subTest(name=name):
                response = self.upload(name=name, content=content)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["code"], 0)
                data = response.data["data"]
                self.assertEqual(data["status"], "uploaded")
                self.assertEqual(data["original_name"], name)
                self.assertNotIn("storage_key", data)
                self.assertNotIn("content_hash", data)
                self.assertNotIn("created_by", data)
                document = KnowledgeDocument.objects.get(pk=data["id"])
                path = self.root / document.storage_key
                self.assertTrue(path.is_file())
                self.assertNotIn(name, document.storage_key)
                self.assertEqual(document.size_bytes, path.stat().st_size)

    def test_document_endpoints_require_superuser(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.upload().status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)

    def test_missing_multiple_and_unsupported_files_are_rejected(self):
        responses = [
            self.client.post(self.url, {}, format="multipart"),
            self.client.post(
                self.url,
                {
                    "file": SimpleUploadedFile("a.md", b"a"),
                    "other": SimpleUploadedFile("b.md", b"b"),
                },
                format="multipart",
            ),
            self.client.post(
                self.url,
                {
                    "file": [
                        SimpleUploadedFile("a.md", b"a"),
                        SimpleUploadedFile("b.md", b"b"),
                    ]
                },
                format="multipart",
            ),
            self.upload(name="empty.md", content=b""),
            self.upload(name="invalid.pdf"),
            self.upload(name=".md"),
            self.upload(name="binary.md", content=b"\xff\xfe"),
            self.upload(name="nul.txt", content=b"a\x00b"),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 400)
        self.assertEqual(KnowledgeDocument.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    @override_settings(KNOWLEDGE_MAX_FILE_SIZE=4)
    def test_oversized_file_returns_413(self):
        response = self.upload(content=b"12345")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(KnowledgeDocument.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_duplicate_hash_is_scoped_to_knowledge_base(self):
        content = b"same content"
        self.assertEqual(self.upload(content=content).status_code, 201)
        response = self.upload(name="different-name.txt", content=content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(KnowledgeDocument.objects.count(), 1)
        self.assertEqual(len(self.stored_files()), 1)

        other_url = f"/api/knowledge-bases/{self.other_base.id}/documents/"
        response = self.upload(content=content, url=other_url)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(KnowledgeDocument.objects.count(), 2)
        self.assertEqual(len(self.stored_files()), 2)

    def test_database_failure_cleans_saved_file(self):
        with patch(
            "knowledge.services.knowledge_documents.KnowledgeDocument.objects.create",
            side_effect=IntegrityError("duplicate"),
        ):
            response = self.upload()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(KnowledgeDocument.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_list_returns_complete_ordered_collection_and_cross_base_404(self):
        first = self.upload(name="first.md", content=b"first").data["data"]
        second = self.upload(name="second.md", content=b"second").data["data"]
        response = self.client.get(self.url, {"page": 1, "page_size": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data["data"]), {"items"})
        self.assertEqual(len(response.data["data"]["items"]), 2)
        self.assertEqual(response.data["data"]["items"][0]["id"], second["id"])
        self.assertIn("processed_at", response.data["data"]["items"][0])

        other_url = f"/api/knowledge-bases/{self.other_base.id}/documents/"
        self.assertEqual(self.client.get(other_url).data["data"]["items"], [])
        cross_url = f"{other_url}{first['id']}/"
        self.assertEqual(self.client.delete(cross_url).status_code, 404)
        self.assertEqual(self.client.get("/api/knowledge-bases/0/documents/").status_code, 400)

    def test_upload_dispatches_only_after_commit(self):
        with patch("knowledge.tasks.vectorize_document.apply_async") as dispatch:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(response.data["data"]["status"], "uploaded")
        dispatch.assert_called_once()
        self.assertEqual(
            dispatch.call_args.kwargs["kwargs"],
            {
                "document_id": response.data["data"]["id"],
                "ingestion_version": 1,
            },
        )
        self.assertEqual(dispatch.call_args.kwargs["queue"], "knowledge")

    def test_upload_dispatch_failure_returns_201_with_retryable_failure(self):
        with (
            patch(
                "knowledge.tasks.vectorize_document.apply_async",
                side_effect=RuntimeError("broker unavailable"),
            ),
            patch(
                "knowledge.services.knowledge_documents.transaction.on_commit",
                side_effect=lambda callback: callback(),
            ),
        ):
            response = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["status"], "failed")
        self.assertEqual(
            response.data["data"]["error_message"],
            "向量化任务投递失败，请重试。",
        )

    def test_retry_increments_version_clears_state_and_dispatches(self):
        document_id = self.upload().data["data"]["id"]
        document = KnowledgeDocument.objects.get(pk=document_id)
        KnowledgeDocument.objects.filter(pk=document_id).update(
            status=KnowledgeDocument.Status.FAILED,
            error_message="failed",
            ingestion_task_id="old-task",
            processing_started_at=document.created_at,
            processed_at=document.created_at,
            embedding_profile_hash="old-profile",
        )
        url = f"{self.url}{document_id}/retry/"
        with patch("knowledge.tasks.vectorize_document.apply_async") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(url)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["data"]["status"], "uploaded")
        self.assertEqual(response.data["data"]["error_message"], "")
        document.refresh_from_db()
        self.assertEqual(document.ingestion_version, 2)
        self.assertEqual(document.ingestion_task_id, "")
        self.assertIsNone(document.processing_started_at)
        self.assertIsNone(document.processed_at)
        self.assertEqual(document.embedding_profile_hash, "")
        self.assertEqual(
            dispatch.call_args.kwargs["kwargs"],
            {"document_id": document_id, "ingestion_version": 2},
        )

    def test_retry_rejects_non_failed_cross_base_and_non_admin(self):
        document_id = self.upload().data["data"]["id"]
        url = f"{self.url}{document_id}/retry/"
        for status_value in ("uploaded", "processing", "ready", "deleting"):
            KnowledgeDocument.objects.filter(pk=document_id).update(status=status_value)
            with self.subTest(status=status_value):
                self.assertEqual(self.client.post(url).status_code, 409)
        other_url = (
            f"/api/knowledge-bases/{self.other_base.id}/documents/"
            f"{document_id}/retry/"
        )
        self.assertEqual(self.client.post(other_url).status_code, 404)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(url).status_code, 401)

    def test_retry_dispatch_failure_returns_503_without_second_increment(self):
        document_id = self.upload().data["data"]["id"]
        KnowledgeDocument.objects.filter(pk=document_id).update(
            status=KnowledgeDocument.Status.FAILED,
            error_message="old error",
        )
        with (
            patch(
                "knowledge.tasks.vectorize_document.apply_async",
                side_effect=RuntimeError("broker unavailable"),
            ),
            patch(
                "knowledge.services.knowledge_documents.transaction.on_commit",
                side_effect=lambda callback: callback(),
            ),
        ):
            response = self.client.post(f"{self.url}{document_id}/retry/")
        self.assertEqual(response.status_code, 503)
        document = KnowledgeDocument.objects.get(pk=document_id)
        self.assertEqual(document.ingestion_version, 2)
        self.assertEqual(document.status, KnowledgeDocument.Status.FAILED)
        self.assertEqual(document.error_message, "向量化任务投递失败，请重试。")

    def test_delete_success_and_missing_file_retry(self):
        document_id = self.upload().data["data"]["id"]
        document = KnowledgeDocument.objects.get(pk=document_id)
        path = self.root / document.storage_key
        original_version = document.ingestion_version

        with patch.object(
            KnowledgeDocument,
            "delete",
            side_effect=DatabaseError("stop after invalidation"),
        ):
            response = self.client.delete(f"{self.url}{document_id}/")
        self.assertEqual(response.status_code, 500)
        document.refresh_from_db()
        self.assertEqual(document.ingestion_version, original_version + 1)
        self.assertEqual(document.status, KnowledgeDocument.Status.DELETING)
        KnowledgeDocument.objects.filter(pk=document_id).update(
            status=KnowledgeDocument.Status.UPLOADED
        )

        response = self.client.delete(f"{self.url}{document_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(path.exists())
        self.assertFalse(KnowledgeDocument.objects.filter(pk=document_id).exists())

        document_id = self.upload(name="missing.md", content=b"missing").data["data"]["id"]
        document = KnowledgeDocument.objects.get(pk=document_id)
        (self.root / document.storage_key).unlink()
        response = self.client.delete(f"{self.url}{document_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(KnowledgeDocument.objects.filter(pk=document_id).exists())

    def test_file_delete_failure_is_diagnosable_and_retryable(self):
        document_id = self.upload().data["data"]["id"]
        with patch(
            "knowledge.services.knowledge_documents.KnowledgeFileStorage.delete",
            side_effect=StorageError("failed"),
        ):
            response = self.client.delete(f"{self.url}{document_id}/")
        self.assertEqual(response.status_code, 500)
        document = KnowledgeDocument.objects.get(pk=document_id)
        self.assertEqual(document.status, KnowledgeDocument.Status.DELETING)
        self.assertTrue(document.error_message)
        self.assertTrue((self.root / document.storage_key).exists())

        response = self.client.delete(f"{self.url}{document_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(KnowledgeDocument.objects.filter(pk=document_id).exists())

    def test_database_delete_failure_preserves_record_for_retry(self):
        document_id = self.upload().data["data"]["id"]
        document = KnowledgeDocument.objects.get(pk=document_id)
        path = self.root / document.storage_key
        with patch.object(
            KnowledgeDocument,
            "delete",
            side_effect=DatabaseError("database unavailable"),
        ):
            response = self.client.delete(f"{self.url}{document_id}/")
        self.assertEqual(response.status_code, 500)
        self.assertFalse(path.exists())
        document.refresh_from_db()
        self.assertEqual(document.status, KnowledgeDocument.Status.DELETING)
        self.assertTrue(document.error_message)

        response = self.client.delete(f"{self.url}{document_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(KnowledgeDocument.objects.filter(pk=document_id).exists())
