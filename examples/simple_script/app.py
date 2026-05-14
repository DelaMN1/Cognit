"""Minimal Cognit example for a plain Python script."""

from __future__ import annotations

import logging
import os

from cognit import CognitHandler


def build_logger() -> logging.Logger:
    logger = logging.getLogger("cognit.examples.simple_script")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    logger.addHandler(
        CognitHandler(
            app_name=os.getenv("COGNIT_APP_NAME", "cognit-simple-script"),
            environment=os.getenv("COGNIT_ENVIRONMENT", "development"),
        )
    )
    return logger


def trigger_test_exception() -> None:
    logger = build_logger()
    try:
        raise RuntimeError("simple script example test exception")
    except RuntimeError:
        logger.exception("Simple script example test exception")


if __name__ == "__main__":
    trigger_test_exception()
