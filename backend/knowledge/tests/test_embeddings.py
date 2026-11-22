import json

import httpx
from django.test import SimpleTestCase, override_settings

from knowledge.embeddings import (
    EmbeddingDimensionError,
    EmbeddingRequestError,
    EmbeddingResponseError,
    EmbeddingUnavailableError,
    OpenAICompatibleEmbedder,
    embedding_profile_hash,
)
from system_setting.services import EffectiveModelConfig


def vector(value=1.0):
    return [value] + [0.0] * 2047


class EmbeddingClientTests(SimpleTestCase):
    def config(self, **overrides):
        values = {
            "model_id": 2,
            "provider_id": 1,
            "model_key": "embedding-model",
            "model_type": "embedding",
            "protocol": "openai_compatible",
            "base_url": "https://embedding.example.com/v1/",
            "dimensions": 2048,
            "api_key": "test-secret",
            "parameters": {},
            "extra_config": {},
        }
        values.update(overrides)
        return EffectiveModelConfig(**values)

    def embedder(self, handler, **kwargs):
        return OpenAICompatibleEmbedder(
            self.config(),
            transport=httpx.MockTransport(handler),
            jitter=lambda start, end: 0,
            **kwargs,
        )

    def test_batches_preserve_index_order_and_authorization(self):
        requests = []

        def handler(request):
            requests.append(request)
            inputs = json.loads(request.content)["input"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": vector(index + 1)}
                        for index in reversed(range(len(inputs)))
                    ]
                },
            )

        with self.embedder(handler) as embedder:
            result = embedder.embed(["first", "second"])
        self.assertEqual(result[0][0], 1.0)
        self.assertEqual(result[1][0], 2.0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].headers["Authorization"], "Bearer test-secret"
        )
        self.assertEqual(str(requests[0].url), "https://embedding.example.com/v1/embeddings")
        self.assertNotIn("dimensions", json.loads(requests[0].content))

    def test_dimensions_are_sent_only_when_explicitly_configured(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": vector()}]}
            )

        config = self.config(parameters={"dimensions": 2048})
        with OpenAICompatibleEmbedder(
            config, transport=httpx.MockTransport(handler)
        ) as embedder:
            embedder.embed(["content"])
        self.assertEqual(json.loads(requests[0].content)["dimensions"], 2048)

    def test_empty_input_does_not_send_http(self):
        handler = lambda request: self.fail("HTTP request should not be sent")
        with self.embedder(handler) as embedder:
            self.assertEqual(embedder.embed([]), [])

    def test_retryable_status_and_network_errors_use_bounded_retries(self):
        attempts = []
        sleeps = []

        def handler(request):
            attempts.append(request)
            if len(attempts) < 3:
                return httpx.Response(429)
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": vector()}]}
            )

        with self.embedder(handler, sleep=sleeps.append) as embedder:
            embedder.embed(["content"])
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [1, 2])

        def unavailable(request):
            raise httpx.ConnectError("unavailable", request=request)

        with self.embedder(unavailable, sleep=lambda delay: None) as embedder:
            with self.assertRaises(EmbeddingUnavailableError) as caught:
                embedder.embed(["content"])
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertNotIn("content", str(caught.exception))

    def test_client_errors_are_not_retried(self):
        attempts = []

        def handler(request):
            attempts.append(request)
            return httpx.Response(400, json={"error": "full response"})

        with self.embedder(handler) as embedder:
            with self.assertRaises(EmbeddingRequestError):
                embedder.embed(["content"])
        self.assertEqual(len(attempts), 1)

    def test_response_contract_rejects_invalid_counts_and_indexes(self):
        responses = (
            {"data": []},
            {"data": [{"index": 0, "embedding": vector()}] * 2},
            {"data": [{"index": 1, "embedding": vector()}]},
        )
        for result in responses:
            with self.subTest(result=result):
                handler = lambda request, result=result: httpx.Response(
                    200, json=result
                )
                with self.embedder(handler) as embedder:
                    with self.assertRaises(EmbeddingResponseError):
                        embedder.embed(["content"])

    def test_dimension_non_finite_and_zero_vectors_are_rejected(self):
        vectors = ([1.0] * 2047, [0.0] * 2048)
        for invalid_vector in vectors:
            with self.subTest(size=len(invalid_vector)):
                handler = lambda request, value=invalid_vector: httpx.Response(
                    200,
                    json={"data": [{"index": 0, "embedding": value}]},
                )
                with self.embedder(handler) as embedder:
                    with self.assertRaises(EmbeddingResponseError):
                        embedder.embed(["content"])

        non_finite = [float("nan")] + [0.0] * 2047
        handler = lambda request: httpx.Response(
            200,
            content=json.dumps(
                {"data": [{"index": 0, "embedding": non_finite}]}
            ),
            headers={"Content-Type": "application/json"},
        )
        with self.embedder(handler) as embedder:
            with self.assertRaises(EmbeddingResponseError):
                embedder.embed(["content"])

        handler = lambda request: httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1.0]}]}
        )
        with self.embedder(handler) as embedder:
            with self.assertRaises(EmbeddingDimensionError):
                embedder.embed(["content"])

    @override_settings(KNOWLEDGE_EMBEDDING_MAX_RESPONSE_BYTES=32)
    def test_oversized_response_is_rejected(self):
        handler = lambda request: httpx.Response(
            200, json={"data": [{"index": 0, "embedding": vector()}]}
        )
        with self.embedder(handler) as embedder:
            with self.assertRaises(EmbeddingResponseError):
                embedder.embed(["content"])

    def test_profile_hash_excludes_api_key(self):
        config = self.config()
        rotated = self.config(api_key="rotated-secret")
        self.assertEqual(embedding_profile_hash(config), embedding_profile_hash(rotated))
        self.assertNotIn(config.api_key, embedding_profile_hash(config))
