from pathlib import Path

import pandas as pd
import pytest

from settings import Settings


def test_dataset_loading_is_independent_of_working_directory(tmp_path, monkeypatch):
    dataset = Path(__file__).parents[1] / "dataset/lite.parquet"
    sample = pd.read_parquet(dataset).iloc[0]
    config = Settings(_env_file=None, INSTANCE_ID=sample["instance_id"], DATASET="lite")
    monkeypatch.chdir(tmp_path)
    config.load_problem_statement()
    assert config.PROBLEM_STATEMENT == sample["problem_statement"]


def test_unknown_instance_is_an_explicit_error():
    config = Settings(_env_file=None, INSTANCE_ID="not-a-real-instance", DATASET="lite")
    with pytest.raises(ValueError, match="was not found"):
        config.load_problem_statement()


@pytest.mark.parametrize("field", ["api_key", "model", "INSTANCE_ID"])
def test_runtime_requires_nonempty_settings(field):
    values = dict(
        api_key="test", model="test", INSTANCE_ID="test", PROBLEM_STATEMENT="issue"
    )
    values[field] = ""
    config = Settings(_env_file=None, **values)
    with pytest.raises(ValueError, match=field.upper()):
        config.validate_runtime()
