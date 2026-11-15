import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class APIKeyEncryptionError(Exception):
    """The API key cannot be encrypted or decrypted with the configured key."""


def _get_fernet() -> Fernet:
    key = os.environ.get("SYSTEM_SETTING_ENCRYPTION_KEY") or getattr(
        settings, "SYSTEM_SETTING_ENCRYPTION_KEY", ""
    )
    if not key:
        raise APIKeyEncryptionError("SYSTEM_SETTING_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise APIKeyEncryptionError(
            "SYSTEM_SETTING_ENCRYPTION_KEY has an invalid format."
        ) from exc


def _get_key_version() -> str:
    return os.environ.get("SYSTEM_SETTING_ENCRYPTION_KEY_VERSION", "v1")


def encrypt_api_key(api_key: str) -> tuple[str, str]:
    try:
        ciphertext = _get_fernet().encrypt(api_key.encode("utf-8")).decode("ascii")
    except APIKeyEncryptionError:
        raise
    except Exception as exc:
        raise APIKeyEncryptionError("API key encryption failed.") from exc
    return ciphertext, _get_key_version()


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (APIKeyEncryptionError, InvalidToken, ValueError, UnicodeError) as exc:
        raise APIKeyEncryptionError("The API key cannot be decrypted.") from exc
