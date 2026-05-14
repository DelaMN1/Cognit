"""Deterministic local fallback embeddings."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from cognit.embeddings.base import BaseEmbedder

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class LocalHashEmbedder(BaseEmbedder):
    """Deterministic hashed term-frequency embedder."""

    def __init__(self, *, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        if self.dimensions <= 0:
            raise ValueError("dimensions must be greater than zero.")

        tokens = _TOKEN_PATTERN.findall(text.lower())
        buckets = [0.0] * self.dimensions
        counts = Counter(tokens)
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], byteorder="big") % self.dimensions
            buckets[bucket] += float(count)

        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0.0:
            return buckets
        return [value / norm for value in buckets]
