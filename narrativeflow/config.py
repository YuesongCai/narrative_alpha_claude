"""Centralized configuration via pydantic-settings.

Every other module reads settings from `get_settings()` rather than reaching
into os.environ directly — this keeps the surface explicit and gives us one
place to add validation, secrets handling, or per-env overrides later.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 🤖 AI ----------------------------------------------------------------
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    model_fast: str = Field(default="claude-sonnet-4-6", validation_alias="NARRATIVEFLOW_MODEL_FAST")
    model_deep: str = Field(default="claude-opus-4-7", validation_alias="NARRATIVEFLOW_MODEL_DEEP")

    # Storage --------------------------------------------------------------
    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT / 'data' / 'narrativeflow.db'}",
        validation_alias="NARRATIVEFLOW_DATABASE_URL",
    )

    # HTTP -----------------------------------------------------------------
    host: str = Field(default="127.0.0.1", validation_alias="NARRATIVEFLOW_HOST")
    port: int = Field(default=8000, validation_alias="NARRATIVEFLOW_PORT")

    # Notifications --------------------------------------------------------
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")

    # Operational ----------------------------------------------------------
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    project_root: Path = PROJECT_ROOT

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def data_dir(self) -> Path:
        d = self.project_root / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
