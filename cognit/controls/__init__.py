"""Deduplication and rate-limiting controls for Cognit alerts."""

from cognit.controls.dedupe import DedupeDecision, Deduplicator
from cognit.controls.rate_limiter import RateLimitDecision, RateLimiter

__all__ = [
    "DedupeDecision",
    "Deduplicator",
    "RateLimitDecision",
    "RateLimiter",
]
