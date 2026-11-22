import hashlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from knowledge.models import KnowledgeBase, KnowledgeDocument


class KnowledgeBaseApiTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin",
            password="password",
        )
        self.user = get_user_model().objects.create_user(
            username="user",
            password="password",
        )
        self.client = APIClient()
        self.url = "/api/knowledge-bases/"

    def create_base(self, name="运维制度", description="内部规范"):
        return KnowledgeBase.objects.create(name=name, description=description)

    def test_management_requires_superuser(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_create_detail_update_and_envelope(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            self.url,
            {"name": "  运维制度  ", "description": "  内部规范  "},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], 0)
        data = response.data["data"]
        self.assertEqual(data["name"], "运维制度")
        self.assertEqual(data["description"], "内部规范")
        self.assertEqual(data["document_count"], 0)
        self.assertNotIn("created_by", data)

        detail_url = f"{self.url}{data['id']}/"
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        response = self.client.patch(
            detail_url,
            {"description": "更新后的说明"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["description"], "更新后的说明")
        self.assertEqual(response.data["data"]["name"], "运维制度")
        self.assertEqual(self.client.put(detail_url, {}, format="json").status_code, 405)

    def test_blank_and_overlong_fields_return_field_errors(self):
        self.client.force_authenticate(self.admin)
        invalid_payloads = (
            {"name": "   ", "description": "valid"},
            {"name": "valid", "description": "   "},
            {"name": "n" * 51, "description": "valid"},
            {"name": "valid", "description": "d" * 301},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(self.url, payload, format="json")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(KnowledgeBase.objects.count(), 0)

    def test_duplicate_name_returns_409_on_create_and_update(self):
        first = self.create_base()
        second = self.create_base(name="其他", description="其他说明")
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            self.url,
            {"name": first.name, "description": "重复"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("name", response.data)

        response = self.client.patch(
            f"{self.url}{second.id}/",
            {"name": first.name},
            format="json",
        )
        self.assertEqual(response.status_code, 409)

    def test_list_search_and_pagination_validation(self):
        self.create_base(name="运维制度", description="值班规范")
        self.create_base(name="开发手册", description="发布流程")
        self.client.force_authenticate(self.admin)

        response = self.client.get(self.url, {"keyword": "值班", "page_size": 1})
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["name"], "运维制度")
        self.assertEqual(data["page_size"], 1)

        for params in ({"page": "abc"}, {"page": 0}, {"page_size": -1}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)
        response = self.client.get(self.url, {"page_size": 1000})
        self.assertEqual(response.data["data"]["page_size"], 100)

    def test_nonempty_base_cannot_be_deleted_and_count_is_live(self):
        knowledge_base = self.create_base()
        content = b"content"
        KnowledgeDocument.objects.create(
            knowledge_base=knowledge_base,
            original_name="guide.md",
            storage_key=f"{knowledge_base.id}/guide.md",
            mime_type="text/markdown",
            extension=".md",
            size_bytes=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
            status=KnowledgeDocument.Status.DELETING,
        )
        self.client.force_authenticate(self.admin)

        response = self.client.get(f"{self.url}{knowledge_base.id}/")
        self.assertEqual(response.data["data"]["document_count"], 1)
        response = self.client.delete(f"{self.url}{knowledge_base.id}/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(KnowledgeBase.objects.filter(pk=knowledge_base.id).exists())

        KnowledgeDocument.objects.all().delete()
        response = self.client.delete(f"{self.url}{knowledge_base.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["code"], 0)
        self.assertFalse(KnowledgeBase.objects.filter(pk=knowledge_base.id).exists())
