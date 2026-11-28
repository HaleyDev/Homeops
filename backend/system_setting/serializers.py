from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .crypto import APIKeyEncryptionError, encrypt_api_key
from .models import EMBEDDING_DIMENSIONS, LLMModel, LLMProvider, ModelType
from .validators import validate_base_url, validate_non_sensitive_config


def _validate_config(config):
    try:
        validate_non_sensitive_config(config)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages) from exc
    return config


class LLMProviderSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    clear_api_key = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
    )
    api_key_configured = serializers.SerializerMethodField()

    class Meta:
        model = LLMProvider
        fields = [
            "id",
            "name",
            "slug",
            "protocol",
            "base_url",
            "api_key",
            "clear_api_key",
            "api_key_configured",
            "is_active",
            "extra_config",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_api_key_configured(self, obj):
        return bool(obj.api_key_ciphertext)

    def validate_base_url(self, value):
        try:
            validate_base_url(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate_extra_config(self, value):
        return _validate_config(value)

    def validate(self, attrs):
        raw_key = attrs.get("api_key", "")
        clear_key = attrs.get("clear_api_key", False)
        if clear_key and raw_key:
            raise serializers.ValidationError(
                {"api_key": "A new API key cannot be set while clearing the existing key."}
            )
        if self.instance is None and not raw_key:
            raise serializers.ValidationError(
                {"api_key": "An API key is required for an OpenAI-compatible provider."}
            )
        if (
            self.instance is not None
            and attrs.get("is_active") is False
            and self.instance.models.filter(selected_for__isnull=False).exists()
        ):
            raise serializers.ValidationError(
                {
                    "is_active": (
                        "This provider contains the currently selected model. "
                        "Change the selection first."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        raw_key = validated_data.pop("api_key")
        validated_data.pop("clear_api_key", False)
        try:
            ciphertext, version = encrypt_api_key(raw_key)
        except APIKeyEncryptionError as exc:
            raise serializers.ValidationError(
                {
                    "api_key": (
                        "The API key encryption service is not configured correctly. "
                        "Contact an administrator."
                    )
                }
            ) from exc
        validated_data["api_key_ciphertext"] = ciphertext
        validated_data["api_key_version"] = version
        return super().create(validated_data)

    def update(self, instance, validated_data):
        raw_key = validated_data.pop("api_key", "")
        clear_key = validated_data.pop("clear_api_key", False)
        if clear_key:
            instance.api_key_ciphertext = ""
            instance.api_key_version = ""
        elif raw_key:
            try:
                ciphertext, version = encrypt_api_key(raw_key)
            except APIKeyEncryptionError as exc:
                raise serializers.ValidationError(
                    {
                        "api_key": (
                            "The API key encryption service is not configured correctly. "
                            "Contact an administrator."
                        )
                    }
                ) from exc
            instance.api_key_ciphertext = ciphertext
            instance.api_key_version = version
        return super().update(instance, validated_data)


class LLMModelSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = LLMModel
        fields = [
            "id",
            "provider",
            "provider_name",
            "model_key",
            "display_name",
            "model_type",
            "dimensions",
            "selected_for",
            "parameters",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["selected_for", "created_at", "updated_at"]

    def validate_parameters(self, value):
        return _validate_config(value)

    def validate(self, attrs):
        model_type = attrs.get(
            "model_type",
            self.instance.model_type if self.instance is not None else None,
        )
        dimensions = attrs.get(
            "dimensions",
            self.instance.dimensions if self.instance is not None else None,
        )
        if model_type == ModelType.EMBEDDING and dimensions != EMBEDDING_DIMENSIONS:
            raise serializers.ValidationError(
                {"dimensions": "Embedding models must use exactly 2048 dimensions."}
            )
        if model_type == ModelType.TEXT and dimensions is not None:
            raise serializers.ValidationError(
                {"dimensions": "Text models must not configure dimensions."}
            )
        if self.instance is None:
            return attrs
        selected_for = self.instance.selected_for
        if selected_for is None:
            return attrs
        if attrs.get("is_active") is False:
            raise serializers.ValidationError(
                {
                    "is_active": (
                        "The currently selected model cannot be deactivated. "
                        "Change the selection first."
                    )
                }
            )
        if (
            "model_type" in attrs
            and attrs["model_type"] != selected_for
        ):
            raise serializers.ValidationError(
                {
                    "model_type": (
                        "The type of the currently selected model cannot be changed. "
                        "Change the selection first."
                    )
                }
            )
        provider = attrs.get("provider")
        if provider is not None and not provider.is_active:
            raise serializers.ValidationError(
                {
                    "provider": (
                        "The currently selected model cannot be assigned to an "
                        "inactive provider."
                    )
                }
            )
        return attrs


class SelectionSerializer(serializers.Serializer):
    model_id = serializers.IntegerField(min_value=1)
