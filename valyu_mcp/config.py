"""Configuration for the Valyu MCP server."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    valyu_api_keys: str = ""
    """Comma-separated list of Valyu API keys."""

    valyu_base_url: str = "https://api.valyu.ai/v1"
    """Valyu API base URL."""

    key_retry_interval_seconds: int = 300
    """Seconds between attempts to bring offline keys back online (default 5 min)."""

    request_timeout_seconds: float = 120.0
    """HTTP request timeout to Valyu API."""

    @property
    def api_keys(self) -> list[str]:
        """Return the API keys as a list of non-empty strings."""
        if not self.valyu_api_keys:
            return []
        return [k.strip() for k in self.valyu_api_keys.split(",") if k.strip()]


settings = Settings()
