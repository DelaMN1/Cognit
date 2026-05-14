from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

_TMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp-tests"
_TMP_ROOT.mkdir(exist_ok=True)


@pytest.fixture
def tmp_path() -> Path:
    path = _TMP_ROOT / f"case-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
