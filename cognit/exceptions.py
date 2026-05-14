"""Custom exception types for Cognit."""


class CognitError(Exception):
    """Base exception for Cognit."""


class CognitConfigError(CognitError):
    """Raised when Cognit configuration is invalid."""


class CognitStorageError(CognitError):
    """Raised when storage operations fail."""


class CognitTelegramError(CognitError):
    """Raised when Telegram operations fail."""


class CognitAIError(CognitError):
    """Raised when AI analysis operations fail."""
