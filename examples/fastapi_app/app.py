"""FastAPI example application for Cognit."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from cognit import CognitHandler


def create_app() -> FastAPI:
    app = FastAPI(title="Cognit FastAPI Example")

    logger = logging.getLogger("cognit.examples.fastapi")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    logger.addHandler(
        CognitHandler(
            app_name=os.getenv("COGNIT_APP_NAME", "cognit-fastapi-example"),
            environment=os.getenv("COGNIT_ENVIRONMENT", "development"),
        )
    )

    @app.get("/error")
    async def error_route():
        try:
            raise RuntimeError("fastapi example test exception")
        except RuntimeError:
            logger.exception("FastAPI example test exception")
            return JSONResponse(
                {"ok": False, "error": "Triggered FastAPI example test exception."},
                status_code=500,
            )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
