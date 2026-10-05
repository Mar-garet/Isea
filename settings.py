from datetime import datetime
from pathlib import Path

import pandas as pd
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration read from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    TEST_BED: str = ""
    PROJECT_NAME: str = ""
    INSTANCE_ID: str = ""
    DATASET: str = "lite"
    PROBLEM_STATEMENT: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    )
    LOG_DIR: str = "results/logs"
    DOCKER_IMAGE: str = ""
    TEST_COMMAND: str = ""
    TEST_TIMEOUT: int = Field(default=300, gt=0)

    def load_problem_statement(self) -> None:
        dataset_file = Path(__file__).parent / "dataset" / f"{self.DATASET}.parquet"
        df = pd.read_parquet(dataset_file)
        matches = df[df["instance_id"] == self.INSTANCE_ID]
        if matches.empty:
            raise ValueError(
                f"Instance {self.INSTANCE_ID!r} was not found in {dataset_file}"
            )
        self.PROBLEM_STATEMENT = str(matches.iloc[0]["problem_statement"])

    def validate_runtime(self) -> None:
        for field in ("api_key", "model", "INSTANCE_ID"):
            if not getattr(self, field).strip():
                raise ValueError(f"Missing required setting: {field.upper()}")
        if not self.PROBLEM_STATEMENT:
            self.load_problem_statement()


settings = Settings()
