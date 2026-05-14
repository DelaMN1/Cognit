"""Shared constants for Cognit."""

DEFAULT_APP_NAME = "cognit-app"
DEFAULT_ENVIRONMENT = "development"
INCIDENT_ID_PREFIX = "cog"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

RESERVED_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
