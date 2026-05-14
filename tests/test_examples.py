from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_simple_script_example_imports():
    module = _load_module("example_simple_script", "examples/simple_script/app.py")

    assert callable(module.build_logger)
    assert callable(module.trigger_test_exception)


def test_flask_example_imports_and_exposes_error_route():
    pytest.importorskip("flask")
    module = _load_module("example_flask_app", "examples/flask_app/app.py")

    app = module.create_app()
    routes = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/error" in routes


def test_fastapi_example_imports_and_exposes_error_route():
    pytest.importorskip("fastapi")
    module = _load_module("example_fastapi_app", "examples/fastapi_app/app.py")

    app = module.create_app()
    routes = {route.path for route in app.routes}

    assert "/error" in routes
