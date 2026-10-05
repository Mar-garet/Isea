import pytest
import pydantic_ai.models

from settings import settings
from tools.retriever_tools import invalidate_retriever


@pytest.fixture(autouse=True)
def isolated_project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    for name, value in {
        "TEST_BED": str(root),
        "PROJECT_NAME": "",
        "INSTANCE_ID": "unit-test",
        "DATASET": "lite",
        "PROBLEM_STATEMENT": "Fix the example issue",
        "TEST_COMMAND": "python -m pytest -q",
        "TEST_TIMEOUT": 10,
        "DOCKER_IMAGE": "test-image",
        "api_key": "test-key",
        "model": "test-model",
        "LOG_DIR": str(tmp_path / "logs"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(pydantic_ai.models, "ALLOW_MODEL_REQUESTS", False)
    invalidate_retriever()
    yield root
    invalidate_retriever()
