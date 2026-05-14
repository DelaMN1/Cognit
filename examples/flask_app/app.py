"""Flask example application for Cognit."""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify

from cognit import CognitHandler


def create_app() -> Flask:
    app = Flask(__name__)

    logger = logging.getLogger("cognit.examples.flask")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    logger.addHandler(
        CognitHandler(
            app_name=os.getenv("COGNIT_APP_NAME", "cognit-flask-example"),
            environment=os.getenv("COGNIT_ENVIRONMENT", "development"),
        )
    )

    @app.get("/error")
    def error_route():
        try:
            raise RuntimeError("flask example test exception")
        except RuntimeError:
            logger.exception("Flask example test exception")
            return jsonify({"ok": False, "error": "Triggered Flask example test exception."}), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
