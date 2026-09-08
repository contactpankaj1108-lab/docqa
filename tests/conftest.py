from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.service import DocQAService  # noqa: E402

SAMPLES = ROOT / "samples"


@pytest.fixture
def settings(tmp_path_factory) -> Settings:
    # Short temp root: a long data path plus a long chunk id can exceed
    # Windows' MAX_PATH under a deeply nested checkout.
    base = Path(tempfile.mkdtemp(prefix="dq", dir=tempfile.gettempdir()))
    return Settings(data_dir=base)


@pytest.fixture
def service(settings: Settings) -> DocQAService:
    return DocQAService(settings)


@pytest.fixture
def seeded(service: DocQAService) -> DocQAService:
    """A service with the full sample corpus indexed."""
    for path in sorted(SAMPLES.iterdir()):
        if path.suffix.lower() in {".pdf", ".txt", ".docx"}:
            service.ingest(path.name, path.read_bytes())
    return service
