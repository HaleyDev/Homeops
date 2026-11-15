import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError


_SENSITIVE_KEY_PARTS = (
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
_RESERVED_RUNTIME_KEYS = {"base_url", "model"}


def validate_base_url(value: str) -> None:
    """Validate an OpenAI-compatible API root without embedded secrets."""

    if not value or value != value.strip() or any(c.isspace() for c in value):
        raise ValidationError("The API base URL cannot be empty or contain whitespace.")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise ValidationError("The API base URL is invalid.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError(
            "The API base URL must be an HTTP/HTTPS URL with a valid hostname."
        )
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("The API base URL cannot contain a username or password.")
    if parsed.query or parsed.fragment:
        raise ValidationError(
            "The API base URL cannot contain query parameters or a fragment. "
            "Use dedicated configuration fields."
        )


def validate_non_sensitive_config(value: dict) -> None:
    """Reject credentials and runtime identity fields in JSON settings."""

    if not isinstance(value, dict):
        raise ValidationError("Extra configuration must be a JSON object.")

    def visit(config) -> None:
        if isinstance(config, list):
            for item in config:
                visit(item)
            return
        if not isinstance(config, dict):
            return
        for key, nested in config.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized == "key" or any(
                part in normalized for part in _SENSITIVE_KEY_PARTS
            ):
                raise ValidationError(
                    "Extra configuration cannot contain API keys, tokens, "
                    "passwords, or other secrets."
                )
            if str(key).lower() in _RESERVED_RUNTIME_KEYS:
                raise ValidationError(
                    f'The "{key}" option must be set through its dedicated field.'
                )
            visit(nested)

    visit(value)
