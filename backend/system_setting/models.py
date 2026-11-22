from django.conf import settings
from django.db import models
from django.db.models import F, Q

from .validators import validate_base_url, validate_non_sensitive_config


class ModelType(models.TextChoices):
    TEXT = "text", "文本模型"
    EMBEDDING = "embedding", "Embedding 模型"


EMBEDDING_DIMENSIONS = 2048


class LLMProvider(models.Model):
    class Protocol(models.TextChoices):
        OPENAI_COMPATIBLE = "openai_compatible", "OpenAI 兼容接口"

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=50, unique=True)
    protocol = models.CharField(
        max_length=32,
        choices=Protocol.choices,
        default=Protocol.OPENAI_COMPATIBLE,
    )
    base_url = models.CharField(max_length=500, validators=[validate_base_url])
    api_key_ciphertext = models.TextField(blank=True, default="")
    api_key_version = models.CharField(max_length=16, blank=True, default="")
    is_active = models.BooleanField(default=True)
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        validators=[validate_non_sensitive_config],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_llm_providers",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_llm_providers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "LLM 供应商"
        verbose_name_plural = "LLM 供应商"

    def __str__(self):
        return self.name


class LLMModel(models.Model):
    provider = models.ForeignKey(
        LLMProvider,
        on_delete=models.CASCADE,
        related_name="models",
    )
    model_key = models.CharField(max_length=160)
    display_name = models.CharField(max_length=100)
    model_type = models.CharField(max_length=20, choices=ModelType.choices)
    dimensions = models.PositiveIntegerField(null=True, blank=True)
    selected_for = models.CharField(
        max_length=20,
        choices=ModelType.choices,
        null=True,
        blank=True,
        default=None,
        unique=True,
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        validators=[validate_non_sensitive_config],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "model_key", "model_type"],
                name="uniq_llm_provider_model_type",
            ),
            models.CheckConstraint(
                condition=Q(selected_for__isnull=True)
                | Q(selected_for=F("model_type")),
                name="llm_model_selection_matches_type",
            ),
            models.CheckConstraint(
                condition=Q(
                    model_type=ModelType.EMBEDDING,
                    dimensions=EMBEDDING_DIMENSIONS,
                )
                | Q(model_type=ModelType.TEXT, dimensions__isnull=True),
                name="llm_model_dimensions_valid",
            ),
        ]
        verbose_name = "LLM 模型"
        verbose_name_plural = "LLM 模型"

    def clean(self):
        if self.selected_for == "":
            self.selected_for = None
        if self.selected_for is not None and self.selected_for != self.model_type:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {"selected_for": "The selection category must match the model type."}
            )
        if (
            self.model_type == ModelType.EMBEDDING
            and self.dimensions != EMBEDDING_DIMENSIONS
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {"dimensions": "Embedding models must use exactly 2048 dimensions."}
            )
        if self.model_type == ModelType.TEXT and self.dimensions is not None:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {"dimensions": "Text models must not configure dimensions."}
            )

    def save(self, *args, **kwargs):
        if self.selected_for == "":
            self.selected_for = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.provider.name} / {self.display_name}"
