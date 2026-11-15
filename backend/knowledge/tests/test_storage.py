import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from knowledge.storage import (
    FileSizeLimitError,
    KnowledgeFileStorage,
    StorageError,
    UploadValidationError,
)


class KnowledgeFileStorageTests(SimpleTestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.storage = KnowledgeFileStorage(root=self.root, max_file_size=1024)

    def upload(self, content=b"# hello", name="guide.md"):
        return SimpleUploadedFile(name, content, content_type="text/markdown")

    def stored_files(self):
        return [path for path in self.root.rglob("*") if path.is_file()]

    def test_save_uses_uuid_key_and_preserves_utf8_content(self):
        content = "# 值班规范\n你好".encode()
        original_name, extension = self.storage.clean_original_name(
            "../folder/\x00值班规范.MD"
        )
        stored = self.storage.save(
            self.upload(content=content, name=original_name),
            7,
            extension,
        )

        self.assertEqual(original_name, "值班规范.MD")
        self.assertEqual(extension, ".md")
        self.assertTrue(stored.storage_key.startswith("7/"))
        self.assertNotIn(original_name, stored.storage_key)
        self.assertTrue(stored.storage_key.endswith(".md"))
        path = self.root / stored.storage_key
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(stored.size_bytes, len(content))
        self.assertEqual(len(stored.content_hash), 64)

    def test_invalid_names_are_rejected(self):
        for name in ("", "folder/", ".md", "file.pdf", "a" * 253 + ".md"):
            with self.subTest(name=name):
                with self.assertRaises(UploadValidationError):
                    self.storage.clean_original_name(name)

    def test_invalid_content_and_size_leave_no_files(self):
        cases = (
            (b"", UploadValidationError),
            (b"abc\x00def", UploadValidationError),
            (b"\xff\xfe", UploadValidationError),
        )
        for content, exception_type in cases:
            with self.subTest(content=content):
                with self.assertRaises(exception_type):
                    self.storage.save(self.upload(content=content), 1, ".md")
                self.assertEqual(self.stored_files(), [])

        limited = KnowledgeFileStorage(root=self.root, max_file_size=3)
        with self.assertRaises(FileSizeLimitError):
            limited.save(self.upload(content=b"four"), 1, ".md")
        self.assertEqual(self.stored_files(), [])

    def test_rename_failure_cleans_temporary_file(self):
        with patch("knowledge.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(StorageError):
                self.storage.save(self.upload(), 1, ".md")
        self.assertEqual(self.stored_files(), [])

    def test_delete_is_idempotent_and_rejects_path_escape(self):
        stored = self.storage.save(self.upload(), 1, ".md")
        self.storage.delete(stored.storage_key)
        self.storage.delete(stored.storage_key)
        self.assertEqual(self.stored_files(), [])

        outside = self.root.parent / "outside-knowledge-test.txt"
        outside.write_text("keep", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        for key in ("../outside-knowledge-test.txt", "/absolute/file.md", "1\\file.md"):
            with self.subTest(key=key):
                with self.assertRaises(StorageError):
                    self.storage.delete(key)
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep")
