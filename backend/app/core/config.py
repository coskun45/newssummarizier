"""
Application configuration using Pydantic Settings.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import List, Optional

_DEFAULT_JWT_SECRET = "change-me-in-production-use-32-char-minimum-secret-key"

# Tek yapılandırma dosyası: repo kökündeki .env (backend/app/core/ -> 3 seviye yukarı).
# Docker'da bu yol yoktur (env compose'tan gelir), pydantic dosya yoksa sessizce atlar.
_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Kök .env docker-compose'un POSTGRES_* gibi Settings'te olmayan anahtarlarını da içerir.
        extra="ignore",
    )
    
    # OpenAI Configuration
    openai_api_key: str
    
    # Database
    database_url: str = "postgresql+psycopg2://bulten:changeme@localhost:5432/bulten"
    
    # Application Settings
    app_name: str = "News Summarizer"
    app_version: str = "2.0.0"
    debug: bool = True
    
    # RSS Feed Configuration
    default_feed_url: str = "https://rss.dw.com/atom/rss-de-all"
    feed_refresh_interval: int = 3600  # seconds between scheduled refreshes; default until changed in Ayarlar

    # LangGraph workflow recursion limit. The graph takes a fixed number of steps
    # (rss_fetcher -> article_processor, which loops over all new articles itself),
    # so the number of new articles in a refresh no longer counts against it.
    graph_recursion_limit: int = 100
    
    # Scraping Configuration
    scraping_enabled: bool = True
    scraping_delay: float = 1.0  # seconds between requests
    max_retries: int = 3
    
    # OpenAI Configuration
    default_model: str = "gpt-4o-mini"
    detailed_model: str = "gpt-4o"
    openai_timeout_seconds: float = 60.0  # per-request cap; SDK default (~10min) is otherwise unbounded
    # Output caps per summary type (article input is truncated by truncate_content).
    # Keep in sync with .env.example and the README env table (tests/test_config.py checks).
    max_tokens_output_brief: int = 1500
    max_tokens_output_standard: int = 3000
    max_tokens_output_detailed: int = 10000
    
    # Cost Management
    daily_cost_limit: float = 10.0  # USD
    monthly_cost_limit: float = 100.0  # USD

    # Bulletin report generation
    bulletin_classification_batch_size: int = 15  # articles per LLM classification call
    bulletin_max_articles: int = 400  # hard cap on articles selected for a single report
    bulletin_storage_dir: str = "./bulletin_reports"  # persisted .docx reports, for re-download
    
    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # JWT Authentication
    jwt_secret_key: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours

    # Initial admin account (seeded once on first startup if both are set — see db/seed.py)
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None

    # Local dev only: POST /api/auth/dev-login issues an admin token without a password.
    # Honoured only while DEBUG is also true (Docker forces DEBUG=false). Note that DEBUG
    # defaults to true for local `uvicorn` (and in .env.example), so outside Docker this
    # flag alone is what exposes the passwordless admin login — never set it on a shared host.
    dev_auto_login: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins string into list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @model_validator(mode="after")
    def _reject_default_jwt_secret_outside_debug(self) -> "Settings":
        """A forgeable, well-known JWT secret is only tolerable in local/dev mode."""
        if not self.debug and self.jwt_secret_key == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY is unset (using the known default placeholder) while DEBUG=False. "
                "Set a unique JWT_SECRET_KEY before running in a non-debug environment."
            )
        return self


# Global settings instance
settings = Settings()
