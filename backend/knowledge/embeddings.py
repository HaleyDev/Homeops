import hashlib
import json
import math
import random
import time

import httpx
from django.conf import settings

from system_setting.models import EMBEDDING_DIMENSIONS, ModelType


class EmbeddingError(Exception):
    safe_message = "Embedding 服务调用失败，请稍后手动重试。"


class EmbeddingConfigurationError(EmbeddingError):
    safe_message = "向量模型未配置或不可用，请联系管理员检查系统设置。"


class EmbeddingRequestError(EmbeddingError):
    safe_message = "Embedding 服务拒绝了请求，请检查向量模型和供应商配置。"


class EmbeddingUnavailableError(EmbeddingError):
    safe_message = "Embedding 服务暂时不可用，已自动重试，请稍后手动重试。"


class EmbeddingResponseError(EmbeddingError):
    safe_message = "Embedding 服务返回了无效数据，请检查向量模型配置。"


class EmbeddingDimensionError(EmbeddingResponseError):
    safe_message = "Embedding 返回维度与系统配置不一致，请检查向量模型配置。"


class _RetryableRequest(Exception):
    pass


def embedding_profile_hash(config):
    if (
        config.model_type != ModelType.EMBEDDING
        or config.dimensions != EMBEDDING_DIMENSIONS
    ):
        raise EmbeddingConfigurationError()
    identity = {
        "base_url": config.base_url.rstrip("/"),
        "dimensions": config.dimensions,
        "model_id": config.model_id,
        "model_key": config.model_key,
        "parameters": config.parameters,
        "provider_id": config.provider_id,
    }
    serialized = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        config,
        *,
        transport=None,
        sleep=time.sleep,
        jitter=random.uniform,
    ):
        self.config = config
        self.profile_hash = embedding_profile_hash(config)
        self._sleep = sleep
        self._jitter = jitter
        timeout_seconds = settings.KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS
        self._max_attempts = settings.KNOWLEDGE_EMBEDDING_MAX_ATTEMPTS
        self._max_response_bytes = settings.KNOWLEDGE_EMBEDDING_MAX_RESPONSE_BYTES
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=10),
            transport=transport,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def embed(self, texts):
        if not texts:
            return []

        last_error = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._embed_once(texts)
            except (_RetryableRequest, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self._max_attempts:
                    break
                delay = 2 ** (attempt - 1)
                self._sleep(delay + self._jitter(0, delay * 0.25))
        raise EmbeddingUnavailableError() from last_error

    def _embed_once(self, texts):
        payload = dict(self.config.parameters)
        if (
            "dimensions" in payload
            and payload["dimensions"] != EMBEDDING_DIMENSIONS
        ):
            raise EmbeddingConfigurationError()
        payload.update({"model": self.config.model_key, "input": texts})
        url = f"{self.config.base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        with self._client.stream(
            "POST", url, json=payload, headers=headers
        ) as response:
            if response.status_code == 429 or response.status_code >= 500:
                raise _RetryableRequest()
            if response.status_code != 200:
                raise EmbeddingRequestError()
            body = self._read_limited_body(response)

        try:
            result = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise EmbeddingResponseError() from exc
        return self._validate_response(result, len(texts))

    def _read_limited_body(self, response):
        body = bytearray()
        for part in response.iter_bytes():
            body.extend(part)
            if len(body) > self._max_response_bytes:
                raise EmbeddingResponseError("Embedding 响应体超过大小限制。")
        return bytes(body)

    def _validate_response(self, result, expected_count):
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise EmbeddingResponseError()
        data = result["data"]
        if len(data) != expected_count:
            raise EmbeddingResponseError()

        ordered = [None] * expected_count
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingResponseError()
            index = item.get("index")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < expected_count
                or ordered[index] is not None
            ):
                raise EmbeddingResponseError()
            ordered[index] = self._validate_vector(item.get("embedding"))
        return ordered

    @staticmethod
    def _validate_vector(vector):
        if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionError()
        validated = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EmbeddingResponseError()
            try:
                number = float(value)
            except (OverflowError, ValueError) as exc:
                raise EmbeddingResponseError() from exc
            if not math.isfinite(number):
                raise EmbeddingResponseError()
            validated.append(number)
        if all(value == 0 for value in validated):
            raise EmbeddingResponseError()
        return validated
