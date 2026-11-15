import os
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from .crypto import encrypt_api_key
from .models import LLMModel, LLMProvider, ModelType
from .services import (
    ModelConfigurationError,
    SelectionError,
    clear_selection,
    get_effective_model_config,
    select_model,
)


class LLMConfigurationTestCase(TestCase):
    def setUp(self):
        key_patch = patch.dict(
            os.environ,
            {
                "SYSTEM_SETTING_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SYSTEM_SETTING_ENCRYPTION_KEY_VERSION": "test",
            },
        )
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.admin = get_user_model().objects.create_superuser(
            username="admin",
            password="password",
        )
        self.user = get_user_model().objects.create_user(
            username="user",
            password="password",
        )
        self.client = APIClient()
        self.provider = self.create_provider("primary")

    def create_provider(self, slug, api_key="test-secret"):
        ciphertext, version = encrypt_api_key(api_key)
        return LLMProvider.objects.create(
            name=slug,
            slug=slug,
            base_url="https://llm.example.com/v1",
            api_key_ciphertext=ciphertext,
            api_key_version=version,
        )

    def create_model(self, provider=None, model_key="model-a", **kwargs):
        values = {
            "provider": provider or self.provider,
            "model_key": model_key,
            "display_name": model_key,
            "model_type": ModelType.TEXT,
            "parameters": {"temperature": 0.2},
        }
        values.update(kwargs)
        return LLMModel.objects.create(**values)

    def test_selection_switches_provider_and_clears_old_label(self):
        first = self.create_model()
        other_provider = self.create_provider("secondary")
        second = self.create_model(other_provider, "model-b")

        select_model(ModelType.TEXT, first.id)
        select_model(ModelType.TEXT, second.id)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNone(first.selected_for)
        self.assertEqual(second.selected_for, ModelType.TEXT)

        clear_selection(ModelType.TEXT)
        second.refresh_from_db()
        self.assertIsNone(second.selected_for)

    def test_selection_rejects_type_mismatch_and_inactive_provider(self):
        model = self.create_model()
        with self.assertRaises(SelectionError):
            select_model(ModelType.EMBEDDING, model.id)

        self.provider.is_active = False
        self.provider.save(update_fields=["is_active"])
        with self.assertRaises(SelectionError):
            select_model(ModelType.TEXT, model.id)

    def test_unique_provider_model_type_constraint(self):
        self.create_model(model_key="shared")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_model(model_key="shared")
        embedding = self.create_model(
            model_key="shared",
            model_type=ModelType.EMBEDDING,
        )
        self.assertEqual(embedding.model_type, ModelType.EMBEDDING)

    def test_effective_config_decrypts_key_and_hides_repr(self):
        model = self.create_model()
        select_model(ModelType.TEXT, model.id)

        config = get_effective_model_config(ModelType.TEXT)

        self.assertEqual(config.model_key, "model-a")
        self.assertEqual(config.api_key, "test-secret")
        self.assertEqual(config.parameters, {"temperature": 0.2})
        self.assertNotIn("test-secret", repr(config))

    def test_missing_effective_config_returns_safe_message(self):
        with self.assertRaisesMessage(
            ModelConfigurationError,
            "Text model is not configured. Contact an administrator.",
        ):
            get_effective_model_config(ModelType.TEXT)

    def test_management_api_requires_superuser(self):
        url = "/api/system-setting/llm/providers/"
        anonymous_response = self.client.get(url)
        self.assertIn(anonymous_response.status_code, {401, 403})

        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_provider_create_encrypts_key_and_redacts_response(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/system-setting/llm/providers/",
            {
                "name": "created",
                "slug": "created",
                "protocol": LLMProvider.Protocol.OPENAI_COMPATIBLE,
                "base_url": "https://created.example.com/v1",
                "api_key": "created-secret",
                "extra_config": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        provider = LLMProvider.objects.get(slug="created")
        self.assertTrue(provider.api_key_ciphertext)
        self.assertNotEqual(provider.api_key_ciphertext, "created-secret")
        self.assertTrue(response.data["data"]["api_key_configured"])
        self.assertNotIn("api_key_ciphertext", response.data["data"])
        self.assertNotIn("created-secret", response.content.decode())

    def test_api_key_update_retains_or_clears_without_disclosure(self):
        self.client.force_authenticate(self.admin)
        url = f"/api/system-setting/llm/providers/{self.provider.id}/"
        original_ciphertext = self.provider.api_key_ciphertext

        response = self.client.patch(
            url,
            {"name": "renamed", "api_key": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.api_key_ciphertext, original_ciphertext)
        self.assertNotIn("api_key_ciphertext", response.data["data"])
        self.assertNotIn("test-secret", response.content.decode())

        response = self.client.patch(url, {"clear_api_key": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.api_key_ciphertext, "")
        self.assertFalse(response.data["data"]["api_key_configured"])

    def test_selected_model_and_provider_cannot_be_disabled_or_deleted(self):
        model = self.create_model()
        select_model(ModelType.TEXT, model.id)
        self.client.force_authenticate(self.admin)

        model_url = f"/api/system-setting/llm/models/{model.id}/"
        provider_url = f"/api/system-setting/llm/providers/{self.provider.id}/"
        self.assertEqual(
            self.client.patch(model_url, {"is_active": False}, format="json").status_code,
            400,
        )
        self.assertEqual(self.client.delete(model_url).status_code, 400)
        self.assertEqual(
            self.client.patch(
                provider_url,
                {"is_active": False},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(self.client.delete(provider_url).status_code, 400)

    def test_invalid_url_and_sensitive_json_are_rejected(self):
        self.client.force_authenticate(self.admin)
        url = "/api/system-setting/llm/providers/"
        payload = {
            "name": "invalid",
            "slug": "invalid",
            "protocol": LLMProvider.Protocol.OPENAI_COMPATIBLE,
            "base_url": "https://user:password@llm.example.com/v1",
            "api_key": "another-secret",
            "extra_config": {},
        }
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 400)

        payload["base_url"] = "https://llm.example.com/v1"
        payload["extra_config"] = {"headers": [{"authorization": "secret"}]}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("another-secret", response.content.decode())
