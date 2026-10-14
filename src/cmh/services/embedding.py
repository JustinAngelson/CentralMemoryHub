"""Dedicated-key embeddings. Deterministic tests never call a remote provider."""

import hashlib
import math
import re
from typing import Protocol

import httpx


class EmbeddingUnavailable(RuntimeError):
    pass


class EmbeddingDimensionMismatch(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    dimensions: int
    model: str

    def embed(self, content: str) -> list[float]: ...


def validate_vector(vector, dimensions):
    if not isinstance(vector, list):
        raise EmbeddingUnavailable("Invalid embedding provider response")
    if len(vector) != dimensions:
        raise EmbeddingDimensionMismatch("Embedding provider dimension mismatch")
    if not vector or not all(not isinstance(value, bool)
                             and isinstance(value, (int, float)) and math.isfinite(value)
                             for value in vector):
        raise EmbeddingUnavailable("Invalid embedding provider response")
    if not any(vector):
        raise EmbeddingUnavailable("Empty embedding provider response")
    return [float(value) for value in vector]


class FakeEmbeddingProvider:
    """Stable sparse token vectors; two controlled synonyms support semantic tests."""

    model = "deterministic-test-v1"

    def __init__(self, dimensions=1536):
        self.dimensions = dimensions
        self.fail = False

    def embed(self, content):
        if self.fail:
            raise EmbeddingUnavailable("Synthetic provider outage")
        vector = [0.0] * self.dimensions
        synonyms = {"automobile": "car", "vehicle": "car"}
        for token in re.findall(r"[a-z0-9_]+", content.lower()):
            token = synonyms.get(token, token)
            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big")
            vector[index % self.dimensions] += 1
        norm = math.sqrt(sum(value * value for value in vector))
        return validate_vector([value / norm for value in vector] if norm else vector,
                               self.dimensions)


class OpenAIEmbeddingProvider:
    def __init__(self, key, model="text-embedding-3-small", dimensions=1536):
        self._key = key
        self.model = model
        self.dimensions = dimensions

    def __repr__(self):
        return "<OpenAIEmbeddingProvider; dedicated credential redacted>"

    def embed(self, content):
        if not self._key:
            raise EmbeddingUnavailable("Embedding credential unavailable")
        try:
            # The default transport has no retries. Never log request/response content.
            with httpx.Client(timeout=10.0) as client:
                response = client.post("https://api.openai.com/v1/embeddings", headers={
                    "Authorization": "Bearer " + self._key.get_secret_value(),
                }, json={"model": self.model, "dimensions": self.dimensions, "input": content})
                response.raise_for_status()
                vector = response.json()["data"][0]["embedding"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            raise EmbeddingUnavailable("Embedding provider unavailable") from None
        return validate_vector(vector, self.dimensions)


def build_embedding_provider(settings):
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(settings.embedding_dimensions)
    if settings.env == "test":
        raise RuntimeError("Tests must explicitly select the fake embedding provider")
    return OpenAIEmbeddingProvider(settings.embedding_api_key, settings.embedding_model,
                                   settings.embedding_dimensions)
