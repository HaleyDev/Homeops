from copy import deepcopy
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .crypto import APIKeyEncryptionError, decrypt_api_key
from .models import EMBEDDING_DIMENSIONS, LLMModel, ModelType
from .validators import validate_base_url, validate_non_sensitive_config


class ModelConfigurationError(Exception):
    """A safe, user-facing error for an unusable runtime model selection."""


class SelectionError(Exception):
    """A model selection could not be changed."""


@dataclass(frozen=True)
class EffectiveModelConfig:
    model_id: int
    provider_id: int
    model_key: str
    model_type: str
    protocol: str
    base_url: str
    dimensions: int | None
    api_key: str = field(repr=False)
    parameters: dict = field(default_factory=dict)
    extra_config: dict = field(default_factory=dict)


def _model_type_label(model_type: ModelType) -> str:
    return "text model" if model_type == ModelType.TEXT else "embedding model"


def _coerce_model_type(model_type: ModelType | str) -> ModelType:
    try:
        return ModelType(model_type)
    except ValueError as exc:
        raise ModelConfigurationError("Unsupported model type.") from exc


def get_effective_model_config(
    model_type: ModelType | str,
) -> EffectiveModelConfig:
    """Resolve and validate one immutable configuration snapshot per consumer turn."""

    category = _coerce_model_type(model_type)
    label = _model_type_label(category)
    try:
        model = (
            LLMModel.objects.select_related("provider")
            .get(selected_for=category.value)
        )
    except LLMModel.DoesNotExist as exc:
        raise ModelConfigurationError(
            f"{label.capitalize()} is not configured. Contact an administrator."
        ) from exc
    except LLMModel.MultipleObjectsReturned as exc:
        raise ModelConfigurationError(
            f"The current {label} configuration is invalid. Contact an administrator."
        ) from exc

    provider = model.provider
    if (
        model.model_type != category.value
        or not model.is_active
        or not provider.is_active
        or provider.protocol != provider.Protocol.OPENAI_COMPATIBLE
        or not provider.api_key_ciphertext
    ):
        raise ModelConfigurationError(
            f"The current {label} configuration is unavailable. Contact an administrator."
        )

    if (
        category == ModelType.EMBEDDING
        and model.dimensions != EMBEDDING_DIMENSIONS
    ) or (category == ModelType.TEXT and model.dimensions is not None):
        raise ModelConfigurationError(
            f"The current {label} configuration is unavailable. Contact an administrator."
        )

    try:
        validate_base_url(provider.base_url)
        validate_non_sensitive_config(provider.extra_config)
        validate_non_sensitive_config(model.parameters)
        api_key = decrypt_api_key(provider.api_key_ciphertext)
    except (ValidationError, APIKeyEncryptionError) as exc:
        raise ModelConfigurationError(
            f"The current {label} configuration is unavailable. Contact an administrator."
        ) from exc
    if not api_key:
        raise ModelConfigurationError(
            f"The current {label} configuration is unavailable. Contact an administrator."
        )

    return EffectiveModelConfig(
        model_id=model.id,
        provider_id=provider.id,
        model_key=model.model_key,
        model_type=model.model_type,
        protocol=provider.protocol,
        base_url=provider.base_url,
        dimensions=model.dimensions,
        api_key=api_key,
        parameters=deepcopy(model.parameters),
        extra_config=deepcopy(provider.extra_config),
    )


def select_model(category: ModelType | str, model_id: int) -> LLMModel:
    try:
        model_type = ModelType(category)
    except ValueError as exc:
        raise SelectionError("Unsupported model category.") from exc

    try:
        with transaction.atomic():
            model = (
                LLMModel.objects.select_for_update()
                .select_related("provider")
                .get(pk=model_id)
            )
            if model.model_type != model_type.value:
                raise SelectionError(
                    "The selected model type does not match the selection category."
                )
            if (
                model_type == ModelType.EMBEDDING
                and model.dimensions != EMBEDDING_DIMENSIONS
            ) or (model_type == ModelType.TEXT and model.dimensions is not None):
                raise SelectionError("The model dimensions configuration is invalid.")
            if not model.is_active or not model.provider.is_active:
                raise SelectionError("An inactive model or provider cannot be selected.")
            LLMModel.objects.filter(selected_for=model_type.value).exclude(
                pk=model.pk
            ).update(selected_for=None)
            model.selected_for = model_type.value
            model.save(update_fields=["selected_for", "updated_at"])
            return model
    except LLMModel.DoesNotExist as exc:
        raise SelectionError("Model not found.") from exc
    except IntegrityError as exc:
        raise SelectionError(
            "The model selection changed concurrently. Refresh and try again."
        ) from exc


def clear_selection(category: ModelType | str) -> None:
    try:
        model_type = ModelType(category)
    except ValueError as exc:
        raise SelectionError("Unsupported model category.") from exc
    with transaction.atomic():
        LLMModel.objects.select_for_update().filter(
            selected_for=model_type.value
        ).update(selected_for=None)
